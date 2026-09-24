import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from types import SimpleNamespace

from router_engine import select_model, eligible_models, NoEligibleModelError
from models.models import RoutingMode


def make_model(id_, quality, cost_in, cost_out, latency, reliability, privacy="public"):
    provider = SimpleNamespace(name="test-provider")
    return SimpleNamespace(
        id=id_, friendly_name=id_, is_active=True, provider=provider,
        quality_score=quality, input_cost_per_1k=cost_in, output_cost_per_1k=cost_out,
        avg_latency_ms=latency, reliability_score=reliability, privacy_class=privacy,
    )


def test_cost_mode_prefers_cheapest():
    cheap = make_model("cheap", quality=0.6, cost_in=0.0001, cost_out=0.0001, latency=500, reliability=0.99)
    expensive = make_model("expensive", quality=0.9, cost_in=0.01, cost_out=0.01, latency=500, reliability=0.99)
    decision = select_model([cheap, expensive], RoutingMode.cost, None)
    assert decision.model.id == "cheap"


def test_quality_mode_prefers_highest_quality():
    cheap = make_model("cheap", quality=0.5, cost_in=0.0001, cost_out=0.0001, latency=500, reliability=0.99)
    good = make_model("good", quality=0.95, cost_in=0.01, cost_out=0.01, latency=500, reliability=0.99)
    decision = select_model([cheap, good], RoutingMode.quality, None)
    assert decision.model.id == "good"


def test_speed_mode_prefers_lowest_latency():
    slow = make_model("slow", quality=0.8, cost_in=0.001, cost_out=0.001, latency=3000, reliability=0.99)
    fast = make_model("fast", quality=0.8, cost_in=0.001, cost_out=0.001, latency=100, reliability=0.99)
    decision = select_model([slow, fast], RoutingMode.speed, None)
    assert decision.model.id == "fast"


def test_privacy_filter_excludes_public_models_when_required():
    public = make_model("pub", quality=0.9, cost_in=0.001, cost_out=0.001, latency=200, reliability=0.99, privacy="public")
    private = make_model("priv", quality=0.6, cost_in=0.001, cost_out=0.001, latency=800, reliability=0.97, privacy="private")
    decision = select_model([public, private], RoutingMode.balanced, None, requires_privacy=True)
    assert decision.model.id == "priv"


def test_no_eligible_model_raises():
    public = make_model("pub", quality=0.9, cost_in=0.001, cost_out=0.001, latency=200, reliability=0.99, privacy="public")
    try:
        select_model([public], RoutingMode.balanced, None, requires_privacy=True)
        assert False, "expected NoEligibleModelError"
    except NoEligibleModelError:
        pass


def test_eligible_models_respects_blocklist():
    m1 = make_model("m1", 0.8, 0.001, 0.001, 300, 0.99)
    m2 = make_model("m2", 0.8, 0.001, 0.001, 300, 0.99)
    policy = SimpleNamespace(allowed_model_ids=[], blocked_model_ids=["m1"])
    pool = eligible_models([m1, m2], policy, requires_privacy=False)
    assert [m.id for m in pool] == ["m2"]
