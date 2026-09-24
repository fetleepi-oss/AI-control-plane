from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.api import auth_routes, project_routes, chat_routes, usage_routes

app = FastAPI(
    title="AI Control Plane",
    description="One API for cloud + private AI. Intelligent routing on cost, "
                 "quality, latency, privacy and reliability.",
    version="0.1.0-mvp",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten to real origins before production
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dev convenience: create tables if they don't exist yet. In production this
# is replaced by real migrations (see README "Moving to Alembic").
Base.metadata.create_all(bind=engine)

app.include_router(auth_routes.router)
app.include_router(project_routes.router)
app.include_router(chat_routes.router)
app.include_router(usage_routes.router)


@app.get("/health")
def health():
    return {"status": "ok"}
