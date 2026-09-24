from pydantic import BaseModel, EmailStr


# --- Auth ---
class SignupRequest(BaseModel):
    email: EmailStr
    password: str
    organization_name: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --- Orgs / Projects ---
class ProjectCreate(BaseModel):
    name: str


class ProjectOut(BaseModel):
    id: str
    name: str

    class Config:
        from_attributes = True


# --- API keys ---
class ApiKeyCreate(BaseModel):
    name: str
    rate_limit_per_min: int = 60
    spend_limit_usd: float | None = None


class ApiKeyCreated(BaseModel):
    id: str
    name: str
    key_prefix: str
    raw_key: str  # shown exactly once, at creation time


class ApiKeyOut(BaseModel):
    id: str
    name: str
    key_prefix: str
    revoked: bool

    class Config:
        from_attributes = True


# --- Chat completions (OpenAI-compatible subset) ---
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str = "auto"       # "auto" or a friendly model name from the registry
    messages: list[ChatMessage]
    temperature: float = 0.7
    max_tokens: int = 1024
    stream: bool = False
    metadata: dict | None = None


class RoutingInfo(BaseModel):
    requested_model: str
    selected_model: str
    provider: str
    reasons: list[str]
    fallback_used: bool


class ChatCompletionResponse(BaseModel):
    id: str
    model: str
    routing: RoutingInfo
    choices: list[dict]
    usage: dict
    cost_usd: float
    latency_ms: float


class FeedbackRequest(BaseModel):
    thumbs_up: bool | None = None
    rating: int | None = None
