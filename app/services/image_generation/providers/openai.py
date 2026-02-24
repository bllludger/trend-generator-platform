"""
OpenAI DALL-E provider for image generation.
"""
import base64
from typing import Optional
import httpx
from openai import OpenAI, PermissionDeniedError

from app.services.image_generation.base import (
    ImageGenerationProvider,
    ImageGenerationRequest,
    ImageGenerationResponse,
)


class OpenAIProvider(ImageGenerationProvider):
    """OpenAI DALL-E image generation provider."""
    
    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = config.get("api_key")
        self.timeout = config.get("timeout", 120.0)
        
        if self.api_key:
            self.client = OpenAI(api_key=self.api_key, timeout=self.timeout)
        else:
            self.client = None
    
    def is_available(self) -> bool:
        """Check if OpenAI is configured."""
        return bool(self.api_key and self.client)
    
    def get_supported_models(self) -> list[str]:
        """Get supported OpenAI models."""
        return ["dall-e-2", "dall-e-3"]
    
    def supports_image_editing(self) -> bool:
        """OpenAI supports image editing via dall-e-2."""
        return True
    
    def generate(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        """
        Generate image using OpenAI API.
        
        Note: 
        - dall-e-3: Only supports text-to-image, no editing
        - dall-e-2: Supports both generation and editing
        """
        if not self.is_available():
            raise ValueError("OpenAI provider not configured")
        
        model = request.model or "dall-e-2"
        
        # Image editing (requires dall-e-2 and input image)
        if request.input_image_path and model == "dall-e-2":
            return self._edit_image(request)
        
        # Text-to-image generation
        return self._generate_image(request)
    
    def _generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        """Generate image from text prompt."""
        response = self.client.images.generate(
            model=request.model,
            prompt=request.prompt,
            size=request.size,
            n=1,
        )
        
        image_url = response.data[0].url
        
        # Download image
        with httpx.Client(timeout=self.timeout) as http_client:
            img_response = http_client.get(image_url)
            img_response.raise_for_status()
            content = img_response.content
        
        return ImageGenerationResponse(
            image_url=image_url,
            image_content=content,
            model=request.model,
            provider="openai",
        )
    
    def _edit_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        """Edit image using OpenAI API (dall-e-2 only)."""
        with open(request.input_image_path, "rb") as image_file:
            response = self.client.images.edit(
                model="dall-e-2",  # Only dall-e-2 supports editing
                image=image_file,
                prompt=request.prompt,
                size=request.size,
            )
        
        image_url = response.data[0].url
        
        # Download image
        with httpx.Client(timeout=self.timeout) as http_client:
            img_response = http_client.get(image_url)
            img_response.raise_for_status()
            content = img_response.content
        
        return ImageGenerationResponse(
            image_url=image_url,
            image_content=content,
            model="dall-e-2",
            provider="openai",
        )
