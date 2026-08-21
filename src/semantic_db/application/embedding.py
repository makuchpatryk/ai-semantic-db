from semantic_db.application.ports import EmbeddingProvider
from semantic_db.application.telemetry import Telemetry
from semantic_db.domain.errors import EmbeddingUnavailableError


async def embed_one(embedder: EmbeddingProvider, text: str, telemetry: Telemetry) -> list[float]:
    """Embed a single text and validate dimensions and model response."""
    with telemetry.span(
        "embed",
        embedding_model=embedder.model_name,
        embedding_dim=embedder.dim,
        text_chars=len(text),
    ):
        vectors = await embedder.embed([text])
        if len(vectors) != 1:
            raise EmbeddingUnavailableError(
                f"{embedder.model_name} returned {len(vectors)} vectors for one text"
            )
        vec = vectors[0]
        if len(vec) != embedder.dim:
            raise EmbeddingUnavailableError(
                f"{embedder.model_name} returned {len(vec)} dimensions, expected {embedder.dim}"
            )
        return vec
