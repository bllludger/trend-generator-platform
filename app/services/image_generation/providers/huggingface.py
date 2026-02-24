"""
Hugging Face Inference API provider for image generation.
Supports FLUX, Stable Diffusion, and other models.
"""
from typing import Optional
import httpx

from app.services.image_generation.base import (
    ImageGenerationProvider,
    ImageGenerationRequest,
    ImageGenerationResponse,
)


class HuggingFaceProvider(ImageGenerationProvider):
    """Hugging Face Inference API provider."""
    
    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = config.get("api_key")
        self.api_url = config.get("api_url", "https://api-inference.huggingface.co")
        self.timeout = config.get("timeout", 120.0)
    
    def is_available(self) -> bool:
        """Check if Hugging Face is configured."""
        return bool(self.api_key)
    
    def get_supported_models(self) -> list[str]:
        """Get supported Hugging Face models."""
        return [
            # FLUX models
            "black-forest-labs/FLUX.1-schnell",  # Fastest
            "black-forest-labs/FLUX.1-dev",      # High quality
            # Stable Diffusion
            "stabilityai/stable-diffusion-xl-base-1.0",
            "stabilityai/stable-diffusion-2-1",
            # Others
            "runwayml/stable-diffusion-v1-5",
        ]
    
    def supports_image_editing(self) -> bool:
        """HF supports editing through specific models."""
        return False  # For now, focus on generation
    
    def generate(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        """Generate image using Hugging Face Inference API."""
        if not self.is_available():
            raise ValueError("Hugging Face provider not configured")
        
        model = request.model or "black-forest-labs/FLUX.1-schnell"
        
        # Build API URL for specific model
        url = f"{self.api_url}/models/{model}"
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        
        # Build payload
        payload = {
            "inputs": request.prompt,
        }
        
        # Add optional parameters
        if request.negative_prompt:
            payload["negative_prompt"] = request.negative_prompt
        
        # Add extra params from request
        if request.extra_params:
            # Parameters like num_inference_steps, guidance_scale, seed, etc.
            payload.update(request.extra_params)
        
        # Make API call
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            
            # HF returns binary image data directly
            content = response.content
        
        return ImageGenerationResponse(
            image_content=content,
            model=model,
            provider="huggingface",
        )
