from functools import lru_cache
from typing import Protocol

from google import genai
from google.genai import types

from app.config import get_settings

# Gemini accepts up to 100 texts per embedding request.
_BATCH_SIZE = 100


class Embedder(Protocol):
    """Anything that turns text into vectors. Lets tests swap in a fake."""

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class GeminiEmbedder:
    def __init__(self, api_key: str, model: str, dim: int):
        self._client = genai.Client(api_key=api_key)
        self._model = model
        self._dim = dim

    async def _embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            result = await self._client.aio.models.embed_content(
                model=self._model,
                contents=texts[i : i + _BATCH_SIZE],
                # task_type tells Gemini whether it's embedding a stored passage or a
                # search query; the two are optimized differently for retrieval.
                config=types.EmbedContentConfig(
                    task_type=task_type, output_dimensionality=self._dim
                ),
            )
            vectors.extend(e.values for e in result.embeddings)
        return vectors

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed(texts, "RETRIEVAL_DOCUMENT")

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([text], "RETRIEVAL_QUERY"))[0]


@lru_cache
def get_embedder() -> Embedder:
    s = get_settings()
    return GeminiEmbedder(api_key=s.google_api_key, model=s.embedding_model, dim=s.embedding_dim)
