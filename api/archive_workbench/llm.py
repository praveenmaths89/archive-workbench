"""LiteLLM wrapper. No call is made unless a key is configured."""
from __future__ import annotations

from .config import settings
from .runtime import current


def configured() -> bool:
    return current().configured


def _call_kwargs(model: str | None) -> dict:
    runtime = current()
    kwargs = {
        "model": model or runtime.model,
        "api_key": runtime.api_key or None,
    }
    if runtime.api_base:
        kwargs["api_base"] = runtime.api_base
    return kwargs


def complete(system: str, user: str, model: str | None = None) -> str:
    import litellm

    kwargs = _call_kwargs(model)
    kwargs["messages"] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    resp = litellm.completion(**kwargs)
    return resp.choices[0].message.content or ""


def complete_vision(prompt: str, jpeg: bytes, model: str | None = None) -> str:
    import base64

    import litellm

    b64 = base64.b64encode(jpeg).decode()
    kwargs = _call_kwargs(model)
    kwargs["messages"] = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ],
    }]
    kwargs["max_tokens"] = 8000
    resp = litellm.completion(**kwargs)
    return resp.choices[0].message.content or ""


def embed_api(texts: list[str]) -> list[list[float]]:
    import litellm

    runtime = current()
    kwargs = {
        "model": settings.embedding_model,
        "input": texts,
        "api_key": runtime.api_key or None,
    }
    if runtime.api_base:
        kwargs["api_base"] = runtime.api_base
    resp = litellm.embedding(**kwargs)
    vectors = [item["embedding"] for item in resp.data]
    for vec in vectors:
        if len(vec) != settings.embedding_dim:
            raise RuntimeError(
                f"embedding model returned {len(vec)} dimensions; the database expects {settings.embedding_dim}. "
                "Use a 384-dimension model, or multilingual-e5-small locally."
            )
    return vectors
