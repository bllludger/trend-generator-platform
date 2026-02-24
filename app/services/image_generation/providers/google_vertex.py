"""
Google Vertex AI Imagen provider for image generation.
"""
from typing import Optional
import httpx

from app.services.image_generation.base import (
    ImageGenerationProvider,
    ImageGenerationRequest,
    ImageGenerationResponse,
)


class GoogleVertexProvider(ImageGenerationProvider):
    """Google Vertex AI Imagen provider."""
    
    def __init__(self, config: dict):
        super().__init__(config)
        self.project_id = config.get("project_id")
        self.location = config.get("location", "us-central1")
        self.api_endpoint = config.get("api_endpoint")
        self.access_token = config.get("access_token")  # OAuth2 token
        self.timeout = config.get("timeout", 120.0)
        
        if not self.api_endpoint and self.project_id:
            self.api_endpoint = (
                f"https://{self.location}-aiplatform.googleapis.com/v1/"
                f"projects/{self.project_id}/locations/{self.location}/"
                f"publishers/google/models"
            )
    
    def is_available(self) -> bool:
        """Check if Google Vertex AI is configured."""
        return bool(self.project_id and self.access_token)
    
    def get_supported_models(self) -> list[str]:
        """Get supported Imagen models."""
        return [
            "imagen-3.0-generate-001",
            "imagen-3.0-fast-generate-001",
            "imagegeneration@006",  # Imagen 2
        ]
    
    def supports_image_editing(self) -> bool:
        """Vertex AI supports editing through edit endpoints."""
        return True
    
    def generate(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        """Generate image using Google Vertex AI Imagen."""
        if not self.is_available():
            raise ValueError("Google Vertex AI provider not configured")
        
        model = request.model or "imagen-3.0-fast-generate-001"
        
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        
        # Build request payload
        payload = {
            "instances": [
                {
                    "prompt": request.prompt,
                }
            ],
            "parameters": {
                "sampleCount": 1,
            }
        }
        
        # Add negative prompt
        if request.negative_prompt:
            payload["instances"][0]["negativePrompt"] = request.negative_prompt
        
        # Add aspect ratio (Imagen uses aspect ratio instead of exact size)
        if request.size:
            aspect_ratio = self._size_to_aspect_ratio(request.size)
            payload["parameters"]["aspectRatio"] = aspect_ratio
        
        # Add extra params
        if request.extra_params:
            payload["parameters"].update(request.extra_params)
        
        # Make API call
        url = f"{self.api_endpoint}/{model}:predict"
        
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()
        
        # Extract image from response
        predictions = result.get("predictions", [])
        if not predictions:
            raise ValueError("No predictions returned from Vertex AI")
        
        # Vertex AI returns base64 encoded images
        image_b64 = predictions[0].get("bytesBase64Encoded")
        if not image_b64:
            raise ValueError("No image data in Vertex AI response")
        
        import base64
        content = base64.b64decode(image_b64)
        
        return ImageGenerationResponse(
            image_b64=image_b64,
            image_content=content,
            model=model,
            provider="google_vertex",
        )
    
    def _size_to_aspect_ratio(self, size: str) -> str:
        """Convert size like '1024x1024' to aspect ratio like '1:1'."""
        if "x" not in size:
            return "1:1"
        
        width, height = size.split("x")
        width, height = int(width), int(height)
        
        # Common aspect ratios
        if width == height:
            return "1:1"
        elif width * 9 == height * 16:
            return "9:16"
        elif width * 16 == height * 9:
            return "16:9"
        elif width * 3 == height * 4:
            return "3:4"
        elif width * 4 == height * 3:
            return "4:3"
        else:
            # Return custom ratio
            from math import gcd
            divisor = gcd(width, height)
            return f"{width//divisor}:{height//divisor}"
