from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Project, Membership, ApiKey, RoutingPolicy, User
from app.schemas.schemas import ProjectCreate, ProjectOut, ApiKeyCreate, ApiKeyCreated, ApiKeyOut
from app.auth.dependencies import get_current_user
from app.auth.security import generate_api_key

router = APIRouter(prefix="/v1", tags=["projects"])


def _assert_member(db: Session, user: User, organization_id: str):
    member = (
        db.query(Membership)
        .filter(Membership.user_id == user.id, Membership.organization_id == organization_id)
        .first()
    )
    if not member:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this organization")
    return member


@router.post("/organizations/{organization_id}/projects", response_model=ProjectOut)
def create_project(
    organization_id: str,
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _assert_member(db, user, organization_id)
    project = Project(organization_id=organization_id, name=payload.name)
    db.add(project)
    db.flush()
    # Every project gets a default balanced routing policy so `auto` works immediately.
    db.add(RoutingPolicy(project_id=project.id))
    db.commit()
    db.refresh(project)
    return project


def _assert_project_access(db: Session, user: User, project_id: str) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Project not found")
    _assert_member(db, user, project.organization_id)
    return project


@router.post("/projects/{project_id}/api-keys", response_model=ApiKeyCreated)
def create_api_key(
    project_id: str,
    payload: ApiKeyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _assert_project_access(db, user, project_id)
    raw_key, key_hash, prefix = generate_api_key()
    api_key = ApiKey(
        project_id=project_id,
        name=payload.name,
        key_hash=key_hash,
        key_prefix=prefix,
        rate_limit_per_min=payload.rate_limit_per_min,
        spend_limit_usd=payload.spend_limit_usd,
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    # raw_key is returned exactly once — the hash is all that's ever stored.
    return ApiKeyCreated(id=api_key.id, name=api_key.name, key_prefix=api_key.key_prefix, raw_key=raw_key)


@router.get("/projects/{project_id}/api-keys", response_model=list[ApiKeyOut])
def list_api_keys(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _assert_project_access(db, user, project_id)
    return db.query(ApiKey).filter(ApiKey.project_id == project_id).all()


@router.delete("/api-keys/{key_id}")
def revoke_api_key(
    key_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    api_key = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if not api_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API key not found")
    _assert_project_access(db, user, api_key.project_id)
    api_key.revoked = True
    db.commit()
    return {"id": key_id, "revoked": True}
