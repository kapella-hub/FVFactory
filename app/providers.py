"""Provider protocol definitions for pluggable backends."""
from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for text generation providers."""

    def generate(self, prompt: str, system: str | None = None,
                 temperature: float = 0.7, max_tokens: int = 1500,
                 json_mode: bool = False) -> str: ...

    def generate_json(self, prompt: str, system: str | None = None,
                      temperature: float = 0.7, max_tokens: int = 1500) -> dict: ...


@runtime_checkable
class ImageProvider(Protocol):
    """Protocol for image generation providers."""

    def generate(self, prompt: str, width: int, height: int,
                 output_path: str) -> str: ...

    def generate_batch(self, prompts: list[str], width: int, height: int,
                       output_dir: str) -> list[str]: ...


@runtime_checkable
class VideoProvider(Protocol):
    """Protocol for image-to-video motion providers."""

    def generate(self, image_path: str, prompt: str,
                 output_path: str, duration: float = 5.0) -> str: ...
