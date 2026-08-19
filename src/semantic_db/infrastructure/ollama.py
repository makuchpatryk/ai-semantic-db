import httpx

from semantic_db.domain.errors import EmbeddingUnavailableError

EMBED_TIMEOUT_SECONDS = 60.0


class OllamaEmbeddingProvider:
    """Embeds through Ollama's batch endpoint (`/api/embed`; `/api/embeddings` is the
    legacy single-text one)."""

    def __init__(self, base_url: str, model_name: str, dim: int) -> None:
        self.model_name = model_name
        self.dim = dim
        self._base_url = base_url.rstrip("/")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        payload = {"model": self.model_name, "input": texts}
        try:
            async with httpx.AsyncClient(timeout=EMBED_TIMEOUT_SECONDS) as client:
                response = await client.post(f"{self._base_url}/api/embed", json=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as exc:
            raise EmbeddingUnavailableError(
                f"Ollama at {self._base_url} rejected the request "
                f"({exc.response.status_code}). Is the model pulled? "
                f"Try: ollama pull {self.model_name}"
            ) from exc
        except httpx.HTTPError as exc:
            raise EmbeddingUnavailableError(
                f"cannot reach Ollama at {self._base_url} ({exc}). Try: ollama serve"
            ) from exc

        embeddings = body.get("embeddings")
        if not isinstance(embeddings, list) or not embeddings:
            raise EmbeddingUnavailableError(
                f"Ollama at {self._base_url} returned no embeddings for {self.model_name}"
            )
        return [[float(value) for value in vector] for vector in embeddings]
