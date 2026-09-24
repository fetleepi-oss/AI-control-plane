"""
The routing engine.

Deliberately NOT an LLM-based router (see architecture doc, "cost control for
your own business" — don't spend an expensive model call deciding which cheap
model to use). This is a transparent, deterministic scoring function over the
model registry, filtered by policy first, scored second.

Every decision returns a list of short human-readable reasons, because "why did
you pick this model" is a first-class product requirement, not an afterthought.
"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from models import ModelEntry, RoutingPolicy, RoutingMode


@dataclass
class RoutingDecision:
    model: ModelEntry
    reasons: list[str] = field(default_factory=list)
    estimated_cost_usd: float = 0.0


class NoEligibleModelError(Exception):
    pass


def _normalize(value: float, low: float, high: float) -> float:
    """Map value into [0,1], higher = better. Guards against a degenerate range."""
    if high <= low:
        return 0.5
    return max(0.0, min(1.0, (value - low) / (high - low)))


def _estimate_cost(model: ModelEntry, input_tokens: int, output_tokens: int) -> float:
    return (
        (input_tokens / 1000.0) * model.input_cost_per_1k
        + (output_tokens / 1000.0) * model.output_cost_per_1k
    )


def eligible_models(
    candidates: list[ModelEntry],
    policy: RoutingPolicy | None,
    requires_privacy: bool,
) -> list[ModelEntry]:
    """Apply hard policy filters before any scoring happens."""
    result = []
    for m in candidates:
        if not m.is_active:
            continue
        if requires_privacy and m.privacy_class == "public":
            continue
        if policy:
            if policy.allowed_model_ids and str(m.id) not in policy.allowed_model_ids:
                continue
            if policy.blocked_model_ids and str(m.id) in policy.blocked_model_ids:
                continue
        result.append(m)
    return result


def select_model(
    candidates: list[ModelEntry],
    mode: RoutingMode,
    policy: RoutingPolicy | None,
    input_tokens: int = 500,
    output_tokens: int = 500,
    requires_privacy: bool = False,
) -> RoutingDecision:
    pool = eligible_models(candidates, policy, requires_privacy)
    if not pool:
        raise NoEligibleModelError(
            "No model satisfies the current routing policy "
            f"(privacy_required={requires_privacy})."
        )

    # Weight profile: explicit mode overrides policy weights for that request.
    if mode == RoutingMode.cost:
        w = dict(quality=0.15, cost=0.55, latency=0.15, reliability=0.10, privacy=0.05)
    elif mode == RoutingMode.speed:
        w = dict(quality=0.15, cost=0.10, latency=0.55, reliability=0.15, privacy=0.05)
    elif mode == RoutingMode.quality:
        w = dict(quality=0.60, cost=0.10, latency=0.10, reliability=0.15, privacy=0.05)
    elif mode == RoutingMode.privacy:
        w = dict(quality=0.20, cost=0.15, latency=0.10, reliability=0.15, privacy=0.40)
    elif policy:
        w = dict(
            quality=policy.weight_quality, cost=policy.weight_cost,
            latency=policy.weight_latency, reliability=policy.weight_reliability,
            privacy=policy.weight_privacy,
        )
    else:  # balanced default
        w = dict(quality=0.30, cost=0.25, latency=0.20, reliability=0.20, privacy=0.05)

    costs = [_estimate_cost(m, input_tokens, output_tokens) for m in pool]
    latencies = [m.avg_latency_ms or 1000.0 for m in pool]
    min_cost, max_cost = min(costs), max(costs)
    min_lat, max_lat = min(latencies), max(latencies)

    scored = []
    for m, cost in zip(pool, costs):
        cost_score = 1.0 - _normalize(cost, min_cost, max_cost)          # cheaper = higher score
        latency_score = 1.0 - _normalize(m.avg_latency_ms or 1000.0, min_lat, max_lat)  # faster = higher
        privacy_score = 1.0 if m.privacy_class != "public" else 0.3

        score = (
            w["quality"] * m.quality_score
            + w["cost"] * cost_score
            + w["latency"] * latency_score
            + w["reliability"] * m.reliability_score
            + w["privacy"] * privacy_score
        )
        scored.append((score, m, cost, cost_score, latency_score))

    scored.sort(key=lambda t: t[0], reverse=True)
    best_score, best_model, best_cost, cost_score, latency_score = scored[0]

    reasons = [f"routing mode: {mode.value}"]
    if requires_privacy:
        reasons.append("privacy required → restricted to approved/private models")
    if cost_score > 0.6:
        reasons.append("among the cheaper eligible options")
    if latency_score > 0.6:
        reasons.append("among the faster eligible options")
    if best_model.quality_score >= 0.75:
        reasons.append("meets high quality threshold")
    if best_model.reliability_score >= 0.99:
        reasons.append("high provider reliability")
    reasons.append(f"score {best_score:.3f} (highest of {len(pool)} eligible models)")

    return RoutingDecision(model=best_model, reasons=reasons, estimated_cost_usd=best_cost)


def fallback_order(decision: RoutingDecision, pool: list[ModelEntry]) -> list[ModelEntry]:
    """Ordered list of alternates to try if the primary model call fails."""
    others = [m for m in pool if m.id != decision.model.id]
    others.sort(key=lambda m: (-m.reliability_score, m.avg_latency_ms or 1e9))
    return others
