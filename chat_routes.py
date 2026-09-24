import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models.models import (
    ModelEntry, ProviderConfig, RoutingPolicy, RoutingMode, ApiKey, Project,
    RequestLog, RequestStatus, Feedback,
)
from schemas.schemas import (
    ChatCompletionRequest, ChatCompletionResponse, RoutingInfo, FeedbackRequest,
)
from auth.dependencies import get_current_api_key, get_project_for_key
from app.routing.router_engine import select_model, fallback_order, NoEligibleModelError, eligible_models
from app.providers.executor import execute_with_fallback, ProviderExecutionError
from app.core.limits import check_rate_limit, check_budget, RateLimitExceeded, BudgetExceeded

router = APIRouter(prefix="/v1", tags=["chat"])


def _mode_from_model_field(model_field: str) -> RoutingMode | None:
    try:
        return RoutingMode(model_field)
    except ValueError:
        return None


@router.get("/models")
def list_models(db: Session = Depends(get_db), api_key: ApiKey = Depends(get_current_api_key)):
    models = db.query(ModelEntry).filter(ModelEntry.is_active == True).all()  # noqa: E712
    return {
        "data": [
            {
                "id": m.friendly_name,
                "provider": m.provider.name,
                "context_length": m.context_length,
                "input_cost_per_1k": m.input_cost_per_1k,
                "output_cost_per_1k": m.output_cost_per_1k,
                "privacy_class": m.privacy_class,
            }
            for m in models
        ]
    }


@router.post("/chat/completions", response_model=ChatCompletionResponse)
def chat_completions(
    payload: ChatCompletionRequest,
    db: Session = Depends(get_db),
    api_key: ApiKey = Depends(get_current_api_key),
    project: Project = Depends(get_project_for_key),
):
    # 1. Rate limit + budget checks happen before any provider call.
    try:
        check_rate_limit(api_key)
        check_budget(db, project.id)
    except RateLimitExceeded as e:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(e))
    except BudgetExceeded as e:
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, str(e))

    # 2. Resolve the candidate pool: all active models, filtered to what
    #    this project/key is allowed to use.
    candidates = (
        db.query(ModelEntry)
        .join(ProviderConfig)
        .filter(ModelEntry.is_active == True)  # noqa: E712
        .all()
    )
    if api_key.allowed_models:
        candidates = [m for m in candidates if m.friendly_name in api_key.allowed_models]
    if not candidates:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No models available for this API key.")

    policy = db.query(RoutingPolicy).filter(RoutingPolicy.project_id == project.id).first()
    requires_privacy = bool(payload.metadata and payload.metadata.get("sensitive"))

    # 3. Decide which model to use.
    explicit_mode = _mode_from_model_field(payload.model)
    if explicit_mode or payload.model == "auto":
        mode = explicit_mode or (policy.default_mode if policy else RoutingMode.balanced)
        pool_for_scoring = candidates
    else:
        # Client asked for a specific model by name.
        named = [m for m in candidates if m.friendly_name == payload.model]
        if not named:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown model '{payload.model}'.")
        pool_for_scoring = named
        mode = RoutingMode.balanced

    try:
        decision = select_model(
            pool_for_scoring, mode, policy,
            input_tokens=sum(len(m.content) // 4 for m in payload.messages),
            output_tokens=payload.max_tokens,
            requires_privacy=requires_privacy,
        )
    except NoEligibleModelError as e:
        _log_request(db, project, api_key, payload.model, None, [str(e)], RequestStatus.blocked, error=str(e))
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    fallback_pool = eligible_models(candidates, policy, requires_privacy)
    fallbacks = fallback_order(decision, fallback_pool)[:2]  # cap fallback depth for latency's sake

    # 4. Execute, with automatic fallback if the primary model errors.
    try:
        response, model_used, fallback_used, attempted, latency_ms = execute_with_fallback(
            decision.model, fallbacks,
            messages=[m.dict() for m in payload.messages],
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
            stream=False,
        )
    except ProviderExecutionError as e:
        _log_request(
            db, project, api_key, payload.model, decision.model, decision.reasons,
            RequestStatus.error, error=str(e),
        )
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e))

    usage = getattr(response, "usage", None)
    input_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
    output_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
    cost = (
        (input_tokens / 1000.0) * model_used.input_cost_per_1k
        + (output_tokens / 1000.0) * model_used.output_cost_per_1k
    )

    request_row = _log_request(
        db, project, api_key, payload.model, model_used, decision.reasons,
        RequestStatus.success, input_tokens=input_tokens, output_tokens=output_tokens,
        cost=cost, latency_ms=latency_ms, fallback_used=fallback_used,
    )

    reasons = list(decision.reasons)
    if fallback_used:
        reasons.append(f"primary model failed; fell back to {model_used.friendly_name}")

    return ChatCompletionResponse(
        id=request_row.id,
        model=model_used.friendly_name,
        routing=RoutingInfo(
            requested_model=payload.model,
            selected_model=model_used.friendly_name,
            provider=model_used.provider.name,
            reasons=reasons,
            fallback_used=fallback_used,
        ),
        choices=[c.model_dump() if hasattr(c, "model_dump") else dict(c) for c in response.choices],
        usage={"prompt_tokens": input_tokens, "completion_tokens": output_tokens},
        cost_usd=round(cost, 6),
        latency_ms=round(latency_ms, 1),
    )


def _log_request(
    db, project, api_key, requested_model, selected_model, reasons, status_,
    input_tokens=0, output_tokens=0, cost=0.0, latency_ms=0.0, fallback_used=False, error=None,
):
    row = RequestLog(
        id=str(uuid.uuid4()),
        project_id=project.id,
        api_key_id=api_key.id,
        requested_model=requested_model,
        selected_model_id=selected_model.id if selected_model else None,
        routing_reason=reasons,
        status=status_,
        error_message=error,
        fallback_used=fallback_used,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost,
        latency_ms=latency_ms,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/requests")
def list_requests(
    db: Session = Depends(get_db),
    project: Project = Depends(get_project_for_key),
    limit: int = 50,
):
    rows = (
        db.query(RequestLog)
        .filter(RequestLog.project_id == project.id)
        .order_by(RequestLog.created_at.desc())
        .limit(min(limit, 200))
        .all()
    )
    return [
        {
            "id": r.id, "requested_model": r.requested_model,
            "selected_model": r.selected_model_id, "status": r.status,
            "cost_usd": r.cost_usd, "latency_ms": r.latency_ms,
            "fallback_used": r.fallback_used, "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@router.get("/requests/{request_id}")
def get_request(
    request_id: str, db: Session = Depends(get_db), project: Project = Depends(get_project_for_key),
):
    row = db.query(RequestLog).filter(RequestLog.id == request_id, RequestLog.project_id == project.id).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    return {
        "id": row.id, "requested_model": row.requested_model,
        "selected_model_id": row.selected_model_id, "routing_reason": row.routing_reason,
        "status": row.status, "error_message": row.error_message, "fallback_used": row.fallback_used,
        "input_tokens": row.input_tokens, "output_tokens": row.output_tokens,
        "cost_usd": row.cost_usd, "latency_ms": row.latency_ms, "created_at": row.created_at.isoformat(),
    }


@router.post("/requests/{request_id}/feedback")
def submit_feedback(
    request_id: str, payload: FeedbackRequest,
    db: Session = Depends(get_db), project: Project = Depends(get_project_for_key),
):
    row = db.query(RequestLog).filter(RequestLog.id == request_id, RequestLog.project_id == project.id).first()
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    existing = db.query(Feedback).filter(Feedback.request_id == request_id).first()
    if existing:
        existing.thumbs_up = payload.thumbs_up
        existing.rating = payload.rating
    else:
        db.add(Feedback(request_id=request_id, thumbs_up=payload.thumbs_up, rating=payload.rating))
    db.commit()
    return {"request_id": request_id, "recorded": True}
