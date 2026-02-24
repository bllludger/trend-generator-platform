"""
Replicate API provider for image generation.
Supports FLUX and other models.
"""
from typing import Optional
import httpx
import time

from app.services.image_generation.base import (
    ImageGenerationProvider,
    ImageGenerationRequest,
    ImageGenerationResponse,
)


class ReplicateProvider(ImageGenerationProvider):
    """Replicate API provider for image generation."""
    
    def __init__(self, config: dict):
        super().__init__(config)
        self.api_token = config.get("api_token")
        self.api_url = config.get("api_url", "https://api.replicate.com/v1")
        self.timeout = config.get("timeout", 120.0)
        self.poll_interval = config.get("poll_interval", 2.0)
    
    def is_available(self) -> bool:
        """Check if Replicate is configured."""
        return bool(self.api_token)
    
    def get_supported_models(self) -> list[str]:
        """Get supported Replicate models."""
        return [
            # FLUX models
            "black-forest-labs/flux-1.1-pro-ultra",  # Most powerful
            "black-forest-labs/flux-1.1-pro",        # Fast professional
            "black-forest-labs/flux-dev",            # Dev version
            "black-forest-labs/flux-schnell",        # Fastest
            # Stable Diffusion
            "stability-ai/sdxl",
        ]
    
    def supports_image_editing(self) -> bool:
        """Replicate supports editing through FLUX Fill models."""
        return True
    
    def generate(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
        """Generate image using Replicate API."""
        if not self.is_available():
            raise ValueError("Replicate provider not configured")
        
        model = request.model or "black-forest-labs/flux-schnell"
        
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }
        
        # Build payload
        payload = {
            "version": self._get_model_version(model),
            "input": {
                "prompt": request.prompt,
            }
        }
        
        # Add size/dimensions
        if "x" in request.size:
            width, height = request.size.split("x")
            payload["input"]["width"] = int(width)
            payload["input"]["height"] = int(height)
        
        # Add negative prompt
        if request.negative_prompt:
            payload["input"]["negative_prompt"] = request.negative_prompt
        
        # Add extra params
        if request.extra_params:
            payload["input"].update(request.extra_params)
        
        # Create prediction
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(
                f"{self.api_url}/predictions",
                headers=headers,
                json=payload
            )
            response.raise_for_status()
            prediction = response.json()
        
        # Poll for completion
        prediction_url = prediction["urls"]["get"]
        image_url = self._wait_for_completion(prediction_url, headers)
        
        # Download image
        with httpx.Client(timeout=self.timeout) as client:
            img_response = client.get(image_url)
            img_response.raise_for_status()
            content = img_response.content
        
        return ImageGenerationResponse(
            image_url=image_url,
            image_content=content,
            model=model,
            provider="replicate",
        )
    
    def _get_model_version(self, model: str) -> str:
        """Get specific version for model (would need to be updated periodically)."""
        # These are example versions - in production, fetch dynamically or maintain a registry
        versions = {
            "black-forest-labs/flux-schnell": "latest",
            "black-forest-labs/flux-dev": "latest",
            "black-forest-labs/flux-1.1-pro": "latest",
        }
        return versions.get(model, "latest")
    
    def _wait_for_completion(self, prediction_url: str, headers: dict, max_wait: int = 300) -> str:
        """Poll prediction until complete and return image URL."""
        start_time = time.time()
        
        with httpx.Client(timeout=self.timeout) as client:
            while time.time() - start_time < max_wait:
                response = client.get(prediction_url, headers=headers)
                response.raise_for_status()
                prediction = response.json()
                
                status = prediction["status"]
                
                if status == "succeeded":
                    # Return first output URL
                    output = prediction["output"]
                    if isinstance(output, list) and output:
                        return output[0]
                    elif isinstance(output, str):
                        return output
                    else:
                        raise ValueError(f"Unexpected output format: {output}")
                
                elif status == "failed":
                    error = prediction.get("error", "Unknown error")
                    raise RuntimeError(f"Replicate prediction failed: {error}")
                
                # Still processing
                time.sleep(self.poll_interval)
        
        raise TimeoutError(f"Replicate prediction timed out after {max_wait}s")
