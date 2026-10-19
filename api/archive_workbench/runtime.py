"""The model key and OCR default the worker should use right now.

A value saved in Settings wins. Otherwise the environment is used.
Nothing here is cached past the request or the job, so saving a key
does not need a restart.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import AppSetting

_current: ContextVar["Runtime | None"] = ContextVar("aw_runtime", default=None)

ENGINES = ("tesseract", "ppocr", "claude", "gemini")
LLM_ENGINES = ("claude", "gemini")


@dataclass
class Runtime:
    api_key: str
    model: str
    api_base: str
    provider: str
    ocr_engine: str
    key_source: str  # saved | env | none

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


def _guess_provider(model: str) -> str:
    model = model or ""
    if model.startswith("gemini/"):
        return "gemini"
    if model.startswith("openai/") or model.startswith("gpt-"):
        return "openai"
    if model.startswith("anthropic/") or "claude" in model:
        return "anthropic"
    return "custom"


def _saved(session: Session) -> dict[str, str]:
    rows = session.scalars(select(AppSetting)).all()
    return {row.key: row.value or "" for row in rows}


def load_runtime(session: Session) -> Runtime:
    saved = _saved(session)
    saved_key = saved.get("llm_api_key", "").strip()
    env_key = settings.model_key
    provider = saved.get("llm_provider", "").strip() or _guess_provider(settings.llm_model)
    model = saved.get("llm_model", "").strip() or settings.llm_model
    base = saved.get("llm_api_base", "").strip() or settings.llm_api_base
    engine = saved.get("ocr_engine", "").strip() or settings.ocr_engine
    if engine not in ENGINES:
        engine = "tesseract"
    if saved_key:
        source = "saved"
        key = saved_key
    elif env_key:
        source = "env"
        key = env_key
    else:
        source = "none"
        key = ""
    return Runtime(key, model, base, provider, engine, source)


def current() -> Runtime:
    found = _current.get()
    if found is not None:
        return found
    return Runtime(
        api_key=settings.model_key,
        model=settings.llm_model,
        api_base=settings.llm_api_base,
        provider=_guess_provider(settings.llm_model),
        ocr_engine=settings.ocr_engine if settings.ocr_engine in ENGINES else "tesseract",
        key_source="env" if settings.model_key else "none",
    )


@contextmanager
def use_runtime(runtime: Runtime):
    token = _current.set(runtime)
    try:
        yield runtime
    finally:
        _current.reset(token)


def vision_model(engine: str, runtime: Runtime) -> str:
    if engine == "gemini":
        return runtime.model if runtime.model.startswith("gemini/") else "gemini/gemini-2.0-flash"
    if engine == "claude":
        if runtime.model.startswith("anthropic/") or "claude" in runtime.model:
            return runtime.model
        return "anthropic/claude-sonnet-4-5"
    return runtime.model


def mask_secret(key: str) -> str:
    key = key or ""
    if len(key) < 8:
        return ""
    return f"••••{key[-4:]}"


def put_setting(session: Session, key: str, value: str) -> None:
    row = session.get(AppSetting, key)
    if row is None:
        session.add(AppSetting(key=key, value=value))
    else:
        row.value = value
