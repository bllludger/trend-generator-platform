"""
Factory for creating image generation providers based on configuration.
"""
from typing import Optional
import logging

from app.services.image_generation.base import ImageGenerationProvider
from app.services.image_generation.providers.openai import OpenAIProvider
from app.services.image_generation.providers.huggingface import HuggingFaceProvider
from app.services.image_generation.providers.replicate import ReplicateProvider
from app.services.image_generation.providers.google_vertex import GoogleVertexProvider

# Gemini provider: optional (module may not exist yet)
try:
    from app.services.image_generation.providers.gemini_nano_banana import GeminiNanaBananaProvider
    _GEMINI_PROVIDER = GeminiNanaBananaProvider
except ModuleNotFoundError:
    _GEMINI_PROVIDER = None

logger = logging.getLogger(__name__)


def _get_providers_registry() -> dict:
    """Build provider registry; gemini only if module is present."""
    reg = {
        "openai": OpenAIProvider,
        "huggingface": HuggingFaceProvider,
        "replicate": ReplicateProvider,
        "google_vertex": GoogleVertexProvider,
    }
    if _GEMINI_PROVIDER is not None:
        reg["gemini"] = _GEMINI_PROVIDER
    return reg


class ImageProviderFactory:
    """Factory for creating image generation providers."""
    
    # Provider registry (gemini added only if gemini_nano_banana exists)
    PROVIDERS = _get_providers_registry()

    # Model name hints for provider compatibility checks (low-risk guardrails)
    MODEL_PROVIDER_HINTS = {
        "gemini": ("gemini-",),
        "openai": ("dall-e-", "gpt-image-"),
        "google_vertex": ("imagen-", "imagegeneration@"),
    }
    
    @classmethod
    def create(cls, provider_name: str, config: dict) -> ImageGenerationProvider:
        """
        Create provider instance by name.
        
        Args:
            provider_name: Name of provider (openai, huggingface, replicate, google_vertex)
            config: Provider-specific configuration dict
            
        Returns:
            Initialized provider instance
            
        Raises:
            ValueError: If provider name is unknown
        """
        provider_class = cls.PROVIDERS.get(provider_name.lower())
        
        if not provider_class:
            available = ", ".join(cls.PROVIDERS.keys())
            raise ValueError(
                f"Unknown provider: {provider_name}. "
                f"Available providers: {available}"
            )
        
        logger.info(f"Creating image provider: {provider_name}")
        provider = provider_class(config)
        
        if not provider.is_available():
            logger.warning(f"Provider {provider_name} created but not fully configured")
        
        return provider
    
    @classmethod
    def create_from_settings(cls, settings, provider_override: Optional[str] = None) -> ImageGenerationProvider:
        """
        Create provider from application settings.
        
        Args:
            settings: Application settings object
            provider_override: If set, use this provider name instead of settings.image_provider
                (e.g. "gemini" when admin enables "Nano Banana Pro")
            
        Returns:
            Initialized provider instance based on settings
        """
        provider_name = (provider_override or "").strip() or settings.image_provider
        
        # Build config based on provider
        if provider_name == "openai":
            config = {
                "api_key": settings.openai_api_key,
                "timeout": settings.openai_request_timeout,
            }
        elif provider_name == "huggingface":
            config = {
                "api_key": settings.huggingface_api_key,
                "api_url": getattr(settings, "huggingface_api_url", None),
                "timeout": getattr(settings, "huggingface_timeout", 120.0),
            }
        elif provider_name == "replicate":
            config = {
                "api_token": settings.replicate_api_token,
                "api_url": getattr(settings, "replicate_api_url", None),
                "timeout": getattr(settings, "replicate_timeout", 120.0),
                "poll_interval": getattr(settings, "replicate_poll_interval", 2.0),
            }
        elif provider_name == "google_vertex":
            config = {
                "project_id": settings.google_vertex_project_id,
                "location": getattr(settings, "google_vertex_location", "us-central1"),
                "access_token": settings.google_vertex_access_token,
                "timeout": getattr(settings, "google_vertex_timeout", 120.0),
            }
        elif provider_name == "gemini":
            config = {
                "api_key": getattr(settings, "gemini_api_key", ""),
                "project_id": getattr(settings, "gemini_project_id", ""),
                "location": getattr(settings, "gemini_location", "us-central1"),
                "api_endpoint": getattr(settings, "gemini_api_endpoint", "https://generativelanguage.googleapis.com"),
                "timeout": getattr(settings, "gemini_timeout", 120.0),
                "model": getattr(settings, "gemini_image_model", "gemini-2.5-flash-image"),
                "safety_settings": getattr(settings, "gemini_safety_settings", "") or "",
            }
        else:
            raise ValueError(f"Provider {provider_name} not supported in settings")
        
        return cls.create(provider_name, config)

    @classmethod
    def infer_provider_from_model(cls, model: str | None) -> Optional[str]:
        """Infer provider from model name (best-effort)."""
        if not model:
            return None
        value = model.strip().lower()
        for provider_name, prefixes in cls.MODEL_PROVIDER_HINTS.items():
            for prefix in prefixes:
                if value.startswith(prefix):
                    return provider_name
        return None

    @classmethod
    def is_model_compatible(cls, provider_name: str, model: str | None) -> bool:
        """
        Low-risk compatibility check: only fail when model clearly belongs to another provider.
        """
        if not model:
            return True
        provider = provider_name.strip().lower()
        inferred = cls.infer_provider_from_model(model)
        if inferred and inferred != provider:
            return False
        return True
    
    @classmethod
    def get_available_providers(cls) -> list[str]:
        """Get list of all available provider names."""
        return list(cls.PROVIDERS.keys())
    
    @classmethod
    def get_provider_for_model(cls, model: str, settings) -> Optional[str]:
        """
        Determine which provider should handle a specific model.
        
        Args:
            model: Model name
            settings: Application settings
            
        Returns:
            Provider name or None if no match found
        """
        # Check each provider's supported models
        for provider_name in cls.PROVIDERS.keys():
            try:
                # Create provider to check supported models
                provider = cls.create_from_settings(settings)
                if model in provider.get_supported_models():
                    return provider_name
            except Exception:
                # Provider not configured, skip
                continue
        
        # No match found, return default
        return None
