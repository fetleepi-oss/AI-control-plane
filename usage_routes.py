from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import RequestLog, Project
from app.auth.dependencies import get_project_for_key

router = APIRouter(prefix="/v1", tags=["usage"])


@router.get("/projects/{project_id}/usage")
def usage_summary(
    project_id: str,
    db: Session = Depends(get_db),
    project: Project = Depends(get_project_for_key),
):
    # get_project_for_key already scopes to the caller's own project via their
    # API key; project_id in the path is validated against it here.
    if project.id != project_id:
        return {"error": "This API key is not scoped to the requested project."}

    total = (
        db.query(
            func.count(RequestLog.id),
            func.coalesce(func.sum(RequestLog.cost_usd), 0.0),
            func.coalesce(func.avg(RequestLog.latency_ms), 0.0),
            func.coalesce(func.sum(RequestLog.input_tokens + RequestLog.output_tokens), 0),
        )
        .filter(RequestLog.project_id == project_id)
        .first()
    )
    error_count = (
        db.query(func.count(RequestLog.id))
        .filter(RequestLog.project_id == project_id, RequestLog.status == "error")
        .scalar()
    )
    request_count, total_cost, avg_latency, total_tokens = total
    return {
        "project_id": project_id,
        "requests": request_count,
        "total_cost_usd": round(total_cost, 4),
        "avg_latency_ms": round(avg_latency, 1),
        "total_tokens": total_tokens,
        "error_rate": round((error_count / request_count), 4) if request_count else 0.0,
    }
