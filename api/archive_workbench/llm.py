"""LiteLLM wrapper. No call is made unless a key is configured."""
from __future__ import annotations

from .config import settings


def configured() -> bool:
    return bool(settings.model_key)


def complete(system: str, user: str, model: str | None = None) -> str:
    import litellm

    kwargs = {
        "model": model or settings.llm_model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "api_key": settings.model_key or None,
    }
    if settings.llm_api_base:
        kwargs["api_base"] = settings.llm_api_base
    resp = litellm.completion(**kwargs)
    return resp.choices[0].message.content or ""


def complete_vision(prompt: str, jpeg: bytes, model: str | None = None) -> str:
    import base64

    import litellm

    b64 = base64.b64encode(jpeg).decode()
    kwargs = {
        "model": model or settings.llm_model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ],
        }],
        "api_key": settings.model_key or None,
        "max_tokens": 8000,
    }
    if settings.llm_api_base:
        kwargs["api_base"] = settings.llm_api_base
    resp = litellm.completion(**kwargs)
    return resp.choices[0].message.content or ""


def embed_api(texts: list[str]) -> list[list[float]]:
    import litellm

    kwargs = {
        "model": settings.embedding_model,
        "input": texts,
        "api_key": settings.model_key or None,
    }
    if settings.llm_api_base:
        kwargs["api_base"] = settings.llm_api_base
    resp = litellm.embedding(**kwargs)
    vectors = [item["embedding"] for item in resp.data]
    for vec in vectors:
        if len(vec) != settings.embedding_dim:
            raise RuntimeError(
                f"embedding model returned {len(vec)} dimensions; the database expects {settings.embedding_dim}. "
                "Use a 384-dimension model, or multilingual-e5-small locally."
            )
    return vectors
