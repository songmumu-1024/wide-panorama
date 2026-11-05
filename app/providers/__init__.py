from __future__ import annotations

from ..config import Settings
from .base import GenContext, ImageProvider, ProviderError
from .mock import MockProvider
from .openai_compat import OpenAICompatProvider

__all__ = ["GenContext", "ImageProvider", "ProviderError", "build_provider"]


def build_provider(settings: Settings) -> ImageProvider:
    provider = settings.provider.lower()
    if provider in {"mock", "demo", "offline"}:
        return MockProvider()
    if provider in {"openai", "openai-compatible", "api"}:
        return OpenAICompatProvider(
            base_url=settings.base_url,
            api_key=settings.api_key,
            model=settings.model,
            timeout=settings.request_timeout,
            size_mode=settings.size_mode,
            preset_sizes=settings.preset_sizes,
            enable_edits=settings.enable_edits,
        )
    raise ProviderError(f"未知的 IMAGE_PROVIDER: {settings.provider}")
