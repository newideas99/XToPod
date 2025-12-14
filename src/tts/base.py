"""Base TTS provider interface."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
from pydantic import BaseModel


class TTSConfig(BaseModel):
    """Base configuration for TTS providers."""

    output_dir: Path = Path("output/audio")
    output_format: str = "mp3"
    sample_rate: int = 24000

    # Voice settings
    host1_voice: str = "Kore"
    host2_voice: str = "Puck"
    host1_name: str = "Alex"
    host2_name: str = "Jordan"

    class Config:
        extra = "allow"


class TTSProvider(ABC):
    """Abstract base class for TTS providers."""

    def __init__(self, config: TTSConfig):
        self.config = config
        self.config.output_dir.mkdir(parents=True, exist_ok=True)

    @abstractmethod
    async def generate_audio(
        self,
        script: str,
        output_path: Optional[Path] = None,
    ) -> Path:
        """
        Generate audio from a multi-speaker script.

        Args:
            script: Multi-speaker dialogue script
            output_path: Optional output file path

        Returns:
            Path to the generated audio file
        """
        pass

    @abstractmethod
    async def generate_single_speaker(
        self,
        text: str,
        voice: str,
        output_path: Optional[Path] = None,
    ) -> Path:
        """Generate audio for a single speaker."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name."""
        pass

    @property
    @abstractmethod
    def supports_multi_speaker(self) -> bool:
        """Whether the provider natively supports multi-speaker generation."""
        pass
