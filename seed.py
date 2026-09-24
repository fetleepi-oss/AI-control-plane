"""
Seeds the platform-wide provider/model registry.

Run with:  python -m app.seed
"""
from app.database import SessionLocal, engine, Base
from app.models.models import ProviderConfig, ModelEntry


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(ProviderConfig).count() > 0:
            print("Registry already seeded, skipping.")
            return

        openrouter = ProviderConfig(
            name="openrouter", kind="openrouter", deployment_type="cloud",
            credential_ref="OPENROUTER_API_KEY",
        )
        ollama = ProviderConfig(
            name="ollama-local", kind="ollama", deployment_type="local",
            base_url="http://localhost:11434",
        )
        db.add_all([openrouter, ollama])
        db.flush()

        models = [
            ModelEntry(
                provider_id=openrouter.id, friendly_name="llama3-70b",
                litellm_model="openrouter/meta-llama/llama-3-70b-instruct",
                family="llama", context_length=8192,
                input_cost_per_1k=0.00059, output_cost_per_1k=0.00079,
                avg_latency_ms=900, reliability_score=0.995, quality_score=0.85,
                privacy_class="public",
            ),
            ModelEntry(
                provider_id=openrouter.id, friendly_name="llama3-8b",
                litellm_model="openrouter/meta-llama/llama-3-8b-instruct",
                family="llama", context_length=8192,
                input_cost_per_1k=0.00007, output_cost_per_1k=0.00007,
                avg_latency_ms=400, reliability_score=0.99, quality_score=0.68,
                privacy_class="public",
            ),
            ModelEntry(
                provider_id=openrouter.id, friendly_name="mistral-7b",
                litellm_model="openrouter/mistralai/mistral-7b-instruct",
                family="mistral", context_length=8192,
                input_cost_per_1k=0.00006, output_cost_per_1k=0.00006,
                avg_latency_ms=380, reliability_score=0.99, quality_score=0.65,
                privacy_class="public",
            ),
            ModelEntry(
                provider_id=openrouter.id, friendly_name="mixtral-8x7b",
                litellm_model="openrouter/mistralai/mixtral-8x7b-instruct",
                family="mistral", context_length=32768,
                input_cost_per_1k=0.00024, output_cost_per_1k=0.00024,
                avg_latency_ms=700, reliability_score=0.99, quality_score=0.78,
                privacy_class="public",
            ),
            ModelEntry(
                provider_id=ollama.id, friendly_name="local-llama3",
                litellm_model="ollama/llama3",
                family="llama", context_length=8192,
                input_cost_per_1k=0.0, output_cost_per_1k=0.0,
                avg_latency_ms=1500, reliability_score=0.97, quality_score=0.70,
                privacy_class="private",
            ),
            ModelEntry(
                provider_id=ollama.id, friendly_name="local-mistral",
                litellm_model="ollama/mistral",
                family="mistral", context_length=8192,
                input_cost_per_1k=0.0, output_cost_per_1k=0.0,
                avg_latency_ms=1400, reliability_score=0.97, quality_score=0.66,
                privacy_class="private",
            ),
        ]
        db.add_all(models)
        db.commit()
        print(f"Seeded {len(models)} models across 2 providers.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
