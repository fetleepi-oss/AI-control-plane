from datetime import datetime

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import User, ApiKey, Project
from app.auth.security import decode_access_token, hash_api_key

bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Human/session auth — used by account & org management endpoints."""
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    user_id = decode_access_token(creds.credentials)
    if not user_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found or inactive")
    return user


def get_current_api_key(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> ApiKey:
    """Application auth — used by the OpenAI-compatible endpoints.

    Deliberately returns a generic error message on every failure path so we
    never reveal whether a key exists, is revoked, or is expired.
    """
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    key_hash = hash_api_key(creds.credentials)
    api_key = db.query(ApiKey).filter(ApiKey.key_hash == key_hash).first()
    if not api_key or api_key.revoked:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    if api_key.expires_at and api_key.expires_at < datetime.utcnow():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    return api_key


def get_project_for_key(
    api_key: ApiKey = Depends(get_current_api_key),
    db: Session = Depends(get_db),
) -> Project:
    project = db.query(Project).filter(Project.id == api_key.project_id).first()
    if not project:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API key")
    return project
