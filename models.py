import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Column, String, Boolean, DateTime, ForeignKey, Float, Integer,
    Enum, Text, JSON, UniqueConstraint
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


def gen_uuid():
    return str(uuid.uuid4())


class Role(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    developer = "developer"
    analyst = "analyst"
    billing = "billing"
    viewer = "viewer"


class RoutingMode(str, enum.Enum):
    auto = "auto"
    cost = "cost"
    speed = "speed"
    quality = "quality"
    privacy = "privacy"
    balanced = "balanced"


class RequestStatus(str, enum.Enum):
    success = "success"
    error = "error"
    blocked = "blocked"


# ---------------------------------------------------------------------------
# Tenancy
# ---------------------------------------------------------------------------
class Organization(Base):
    __tablename__ = "organizations"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    memberships = relationship("Membership", back_populates="organization", cascade="all, delete-orphan")
    projects = relationship("Project", back_populates="organization", cascade="all, delete-orphan")
    providers = relationship("ProviderConfig", back_populates="organization", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    memberships = relationship("Membership", back_populates="user", cascade="all, delete-orphan")


class Membership(Base):
    __tablename__ = "memberships"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    user_id = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    organization_id = Column(UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=False)
    role = Column(Enum(Role), nullable=False, default=Role.developer)

    user = relationship("User", back_populates="memberships")
    organization = relationship("Organization", back_populates="memberships")

    __table_args__ = (UniqueConstraint("user_id", "organization_id", name="uq_user_org"),)


class Project(Base):
    __tablename__ = "projects"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    organization_id = Column(UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=False)
    name = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    organization = relationship("Organization", back_populates="projects")
    api_keys = relationship("ApiKey", back_populates="project", cascade="all, delete-orphan")
    routing_policy = relationship("RoutingPolicy", back_populates="project", uselist=False, cascade="all, delete-orphan")
    budgets = relationship("Budget", back_populates="project", cascade="all, delete-orphan")


# ---------------------------------------------------------------------------
# Auth / API keys
# ---------------------------------------------------------------------------
class ApiKey(Base):
    __tablename__ = "api_keys"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    project_id = Column(UUID(as_uuid=False), ForeignKey("projects.id"), nullable=False)
    name = Column(String, nullable=False)
    # Never store the raw key. We store a SHA-256 hash and a short prefix for display.
    key_hash = Column(String, unique=True, nullable=False, index=True)
    key_prefix = Column(String, nullable=False)  # e.g. "sk-live-8f3a" for UI display
    allowed_models = Column(JSON, default=list)       # [] means "all models the project can use"
    allowed_providers = Column(JSON, default=list)    # [] means "all approved providers"
    rate_limit_per_min = Column(Integer, default=60)
    spend_limit_usd = Column(Float, nullable=True)     # lifetime/period cap, enforced with Budget too
    revoked = Column(Boolean, default=False)
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="api_keys")


# ---------------------------------------------------------------------------
# Provider / model registry
# ---------------------------------------------------------------------------
class ProviderConfig(Base):
    """A configured backend the router can dispatch to (cloud or private)."""
    __tablename__ = "providers"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    organization_id = Column(UUID(as_uuid=False), ForeignKey("organizations.id"), nullable=True)  # null = platform-wide
    name = Column(String, nullable=False)              # "openrouter", "ollama-local", ...
    kind = Column(String, nullable=False)               # "openrouter" | "ollama" | "vllm" | ...
    base_url = Column(String, nullable=True)             # for private/self-hosted endpoints
    # Credentials are kept server-side only and never serialized to API responses.
    credential_ref = Column(String, nullable=True)       # name of the env var / secret holding the key
    deployment_type = Column(String, default="cloud")    # "cloud" | "private" | "local"
    region = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)

    organization = relationship("Organization", back_populates="providers")
    models = relationship("ModelEntry", back_populates="provider", cascade="all, delete-orphan")


class ModelEntry(Base):
    """One routable model. Metadata here is what the router scores against."""
    __tablename__ = "models"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    provider_id = Column(UUID(as_uuid=False), ForeignKey("providers.id"), nullable=False)
    friendly_name = Column(String, nullable=False, index=True)   # what clients request, e.g. "llama3-70b"
    litellm_model = Column(String, nullable=False)                # e.g. "openrouter/meta-llama/llama-3-70b-instruct"
    family = Column(String, nullable=True)                        # "llama", "mistral", ...
    context_length = Column(Integer, default=8192)
    input_cost_per_1k = Column(Float, default=0.0)                # USD
    output_cost_per_1k = Column(Float, default=0.0)
    # Rolling stats, updated by the background aggregator from `requests` rows.
    avg_latency_ms = Column(Float, default=0.0)
    reliability_score = Column(Float, default=1.0)   # 0-1, success rate
    quality_score = Column(Float, default=0.7)        # 0-1, seeded manually until feedback accumulates
    privacy_class = Column(String, default="public")  # "public" | "approved" | "private"
    is_active = Column(Boolean, default=True)

    provider = relationship("ProviderConfig", back_populates="models")

    __table_args__ = (UniqueConstraint("friendly_name", "provider_id", name="uq_model_provider"),)


class RoutingPolicy(Base):
    """Per-project router configuration: mode + weights + allow/deny rules."""
    __tablename__ = "routing_policies"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    project_id = Column(UUID(as_uuid=False), ForeignKey("projects.id"), nullable=False, unique=True)
    default_mode = Column(Enum(RoutingMode), default=RoutingMode.balanced)
    weight_quality = Column(Float, default=0.35)
    weight_cost = Column(Float, default=0.25)
    weight_latency = Column(Float, default=0.20)
    weight_reliability = Column(Float, default=0.15)
    weight_privacy = Column(Float, default=0.05)
    allowed_model_ids = Column(JSON, default=list)     # [] = no restriction
    blocked_model_ids = Column(JSON, default=list)
    require_private_for_sensitive = Column(Boolean, default=False)
    fallback_chain = Column(JSON, default=list)         # ordered list of model_ids to try on failure

    project = relationship("Project", back_populates="routing_policy")


class Budget(Base):
    __tablename__ = "budgets"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    project_id = Column(UUID(as_uuid=False), ForeignKey("projects.id"), nullable=False)
    period = Column(String, default="monthly")   # "daily" | "monthly"
    limit_usd = Column(Float, nullable=False)
    action_on_exceed = Column(String, default="block")  # "block" | "downgrade" | "require_approval"

    project = relationship("Project", back_populates="budgets")


# ---------------------------------------------------------------------------
# Observability
# ---------------------------------------------------------------------------
class RequestLog(Base):
    __tablename__ = "requests"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    project_id = Column(UUID(as_uuid=False), ForeignKey("projects.id"), nullable=False, index=True)
    api_key_id = Column(UUID(as_uuid=False), ForeignKey("api_keys.id"), nullable=True)
    requested_model = Column(String, nullable=False)     # "auto" or a friendly name
    selected_model_id = Column(UUID(as_uuid=False), ForeignKey("models.id"), nullable=True)
    routing_reason = Column(JSON, default=list)           # list of short reason strings
    status = Column(Enum(RequestStatus), default=RequestStatus.success)
    error_message = Column(Text, nullable=True)
    fallback_used = Column(Boolean, default=False)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)
    latency_ms = Column(Float, default=0.0)
    cache_hit = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    feedback = relationship("Feedback", back_populates="request", uselist=False, cascade="all, delete-orphan")


class Feedback(Base):
    __tablename__ = "feedback"
    id = Column(UUID(as_uuid=False), primary_key=True, default=gen_uuid)
    request_id = Column(UUID(as_uuid=False), ForeignKey("requests.id"), nullable=False, unique=True)
    rating = Column(Integer, nullable=True)       # 1-5, optional
    thumbs_up = Column(Boolean, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    request = relationship("RequestLog", back_populates="feedback")
