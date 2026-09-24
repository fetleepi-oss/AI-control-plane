import re
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from config import settings


def normalize_db_url(raw: str) -> str:
    if not raw:
        raise RuntimeError(
            "DATABASE_URL is empty. Set it in Render → your web service → "
            "Environment tab, using the Internal Database URL from your Postgres instance."
        )

    url = raw.strip().strip('"').strip("'")

    # Strip an accidentally-pasted "DATABASE_URL=" or "KEY=" prefix
    url = re.sub(r'^[A-Z_]+\s*=\s*', '', url)

    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://") and not url.startswith("postgresql+"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]

    if not url.startswith("postgresql+psycopg://"):
        raise RuntimeError(
            f"DATABASE_URL doesn't look like a Postgres connection string after "
            f"cleanup: starts with '{url[:20]}...'. Check Render's Environment tab "
            f"— the Value field should contain ONLY the URL, nothing else."
        )
    return url


db_url = normalize_db_url(settings.database_url)
print(f"[database] connecting to: {db_url.split('@')[0].split('://')[0]}://***@{db_url.split('@')[-1]}")

engine = create_engine(db_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
