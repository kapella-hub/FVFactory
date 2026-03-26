"""Tests for provider protocol definitions."""
import pytest
from app.providers import LLMProvider, ImageProvider, VideoProvider


class MockLLM:
    def generate(self, prompt: str, system: str | None = None,
                 temperature: float = 0.7, max_tokens: int = 1500,
                 json_mode: bool = False) -> str:
        return "mock response"

    def generate_json(self, prompt: str, system: str | None = None,
                      temperature: float = 0.7, max_tokens: int = 1500) -> dict:
        return {"mock": True}


class MockImage:
    def generate(self, prompt: str, width: int, height: int,
                 output_path: str) -> str:
        return output_path

    def generate_batch(self, prompts: list[str], width: int, height: int,
                       output_dir: str) -> list[str]:
        return [f"{output_dir}/{i}.png" for i in range(len(prompts))]


class MockVideo:
    def generate(self, image_path: str, prompt: str,
                 output_path: str, duration: float = 5.0) -> str:
        return output_path


def test_llm_provider_protocol():
    provider: LLMProvider = MockLLM()
    assert provider.generate("hello") == "mock response"
    assert provider.generate_json("hello") == {"mock": True}


def test_image_provider_protocol():
    provider: ImageProvider = MockImage()
    assert provider.generate("a cat", 1080, 1920, "/tmp/out.png") == "/tmp/out.png"


def test_video_provider_protocol():
    provider: VideoProvider = MockVideo()
    assert provider.generate("/img.png", "zoom in", "/tmp/out.mp4") == "/tmp/out.mp4"
