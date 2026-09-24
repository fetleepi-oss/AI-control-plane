from datetime import datetime, timedelta

import redis
from sqlalchemy.orm import Session
from sqlalchemy import func

from config import settings
from models.models import ApiKey, Budget, RequestLog

_redis = redis.from_url(settings.redis_url, decode_responses=True)


class RateLimitExceeded(Exception):
    pass


class BudgetExceeded(Exception):
    pass


def check_rate_limit(api_key: ApiKey) -> None:
    """Fixed-window per-minute limiter, keyed on the API key."""
    window = datetime.utcnow().strftime("%Y%m%d%H%M")
    redis_key = f"ratelimit:{api_key.id}:{window}"
    count = _redis.incr(redis_key)
    if count == 1:
        _redis.expire(redis_key, 60)
    if count > api_key.rate_limit_per_min:
        raise RateLimitExceeded(
            f"Rate limit exceeded: {api_key.rate_limit_per_min} requests/min for this API key."
        )


def check_budget(db: Session, project_id: str) -> None:
    """Checks all active budgets for a project against actual spend this period."""
    budgets = db.query(Budget).filter(Budget.project_id == project_id).all()
    for budget in budgets:
        since = (
            datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
            if budget.period == "daily"
            else datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        )
        spent = (
            db.query(func.coalesce(func.sum(RequestLog.cost_usd), 0.0))
            .filter(RequestLog.project_id == project_id, RequestLog.created_at >= since)
            .scalar()
        )
        if spent >= budget.limit_usd:
            if budget.action_on_exceed == "block":
                raise BudgetExceeded(
                    f"{budget.period.capitalize()} budget of ${budget.limit_usd:.2f} exceeded "
                    f"(spent ${spent:.2f}). Action: block."
                )
            # "downgrade" and "require_approval" are enforced by the router/UI
            # layer in later phases; Phase 1 surfaces the state, doesn't act on it silently.
