from abc import ABC, abstractmethod


class Storage(ABC):
    @abstractmethod
    def save_job_image(self, job_id: str, filename: str, content: bytes) -> str:
        raise NotImplementedError

    @abstractmethod
    def save_trend_example(self, trend_id: str, content: bytes, ext: str) -> str:
        """Save trend example image; returns full path."""
        raise NotImplementedError
