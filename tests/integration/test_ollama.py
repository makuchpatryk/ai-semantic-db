import httpx
import pytest

from semantic_db.domain.errors import EmbeddingUnavailableError
from semantic_db.infrastructure.ollama import OllamaEmbeddingProvider
from semantic_db.settings import Settings

pytestmark = pytest.mark.integration


@pytest.fixture
def ollama_running() -> None:
    """Skip when no Ollama answers on the configured URL.

    CI has no Ollama — a multi-GB model pull per run buys nothing that the local
    integration run doesn't already cover — so these tests skip there and are the one
    part of the suite CI does not gate on. See PRD 11.
    """
    base_url = Settings().ollama_base_url
    try:
        httpx.get(f"{base_url}/api/tags", timeout=2.0).raise_for_status()
    except httpx.HTTPError:
        pytest.skip(f"no Ollama at {base_url}")


def provider(settings: Settings) -> OllamaEmbeddingProvider:
    return OllamaEmbeddingProvider(
        base_url=settings.ollama_base_url,
        model_name=settings.embedding_model,
        dim=settings.embedding_dim,
    )


async def test_embeds_a_batch_with_the_declared_dimension(ollama_running: None) -> None:
    settings = Settings()
    vectors = await provider(settings).embed(["Title: Hydraulic pump", "Title: Servo motor"])

    assert len(vectors) == 2
    assert all(len(vector) == settings.embedding_dim for vector in vectors)


async def test_same_text_embeds_to_the_same_vector(ollama_running: None) -> None:
    vectors = await provider(Settings()).embed(["Title: Hydraulic pump"] * 2)
    assert vectors[0] == vectors[1]


async def test_unreachable_ollama_names_the_url_and_the_fix() -> None:
    unreachable = OllamaEmbeddingProvider(
        base_url="http://127.0.0.1:1", model_name="bge-m3", dim=1024
    )

    with pytest.raises(EmbeddingUnavailableError, match="ollama serve"):
        await unreachable.embed(["anything"])


async def test_missing_model_is_reported_with_the_pull_command(ollama_running: None) -> None:
    missing = OllamaEmbeddingProvider(
        base_url=Settings().ollama_base_url, model_name="no-such-model", dim=1024
    )

    with pytest.raises(EmbeddingUnavailableError, match="ollama pull no-such-model"):
        await missing.embed(["anything"])
