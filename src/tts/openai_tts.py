"""
OpenAI TTS Provider.

OpenAI TTS offers good quality at low cost:
- 6 voices (alloy, echo, fable, onyx, nova, shimmer)
- ~$7-15/month for daily 30-min podcasts
- Fast generation
- No voice cloning

Good value option when ElevenLabs is too expensive and Gemini isn't available.
"""

from datetime import datetime
from pathlib import Path
from typing import Optional, Literal
import structlog
from io import BytesIO

from openai import AsyncOpenAI

from .base import TTSProvider, TTSConfig

logger = structlog.get_logger()

# Available OpenAI voices
OpenAIVoice = Literal["alloy", "echo", "fable", "onyx", "nova", "shimmer"]


class OpenAITTSConfig(TTSConfig):
    """Configuration for OpenAI TTS."""

    api_key: str
    model: str = "tts-1"  # or "tts-1-hd" for higher quality

    # Available voices: alloy, echo, fable, onyx, nova, shimmer
    host1_voice: OpenAIVoice = "nova"  # Female voice
    host2_voice: OpenAIVoice = "onyx"  # Male voice

    speed: float = 1.0  # 0.25 to 4.0


class OpenAITTS(TTSProvider):
    """
    OpenAI TTS provider.

    Cost-effective option with decent quality.
    Does not natively support multi-speaker - generates per segment.
    """

    def __init__(self, config: OpenAITTSConfig):
        super().__init__(config)
        self.config: OpenAITTSConfig = config
        self.client = AsyncOpenAI(api_key=config.api_key)

    @property
    def name(self) -> str:
        return "openai"

    @property
    def supports_multi_speaker(self) -> bool:
        return False

    async def generate_audio(
        self,
        script: str,
        output_path: Optional[Path] = None,
    ) -> Path:
        """Generate audio from a multi-speaker script."""
        if output_path is None:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            output_path = self.config.output_dir / f"podcast_{timestamp}.{self.config.output_format}"

        # Parse script into segments
        segments = self._parse_script(script)

        if not segments:
            raise ValueError("No dialogue segments found in script")

        logger.info(f"Generating {len(segments)} audio segments with OpenAI TTS")

        # Generate audio for each segment
        audio_segments = []
        for i, (speaker, text) in enumerate(segments):
            voice = self.config.host1_voice if speaker == self.config.host1_name else self.config.host2_voice
            logger.debug(f"Segment {i + 1}/{len(segments)}: {speaker} ({voice})")

            segment_audio = await self._generate_segment(text, voice)
            audio_segments.append(segment_audio)

        # Combine segments using pydub
        combined = await self._combine_segments(audio_segments)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        combined.export(str(output_path), format=self.config.output_format)

        logger.info(f"Audio saved to {output_path}")
        return output_path

    async def generate_single_speaker(
        self,
        text: str,
        voice: str,
        output_path: Optional[Path] = None,
    ) -> Path:
        """Generate audio for a single speaker."""
        if output_path is None:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            output_path = self.config.output_dir / f"audio_{timestamp}.{self.config.output_format}"

        audio_data = await self._generate_segment(text, voice)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(audio_data)

        return output_path

    async def _generate_segment(self, text: str, voice: str) -> bytes:
        """Generate audio for a single text segment."""
        response = await self.client.audio.speech.create(
            model=self.config.model,
            voice=voice,
            input=text,
            speed=self.config.speed,
            response_format="mp3",
        )

        return response.content

    async def _combine_segments(self, segments: list[bytes]):
        """Combine audio segments using pydub."""
        from pydub import AudioSegment

        combined = AudioSegment.empty()

        for segment_bytes in segments:
            segment = AudioSegment.from_mp3(BytesIO(segment_bytes))
            # Add small pause between speakers
            combined += segment + AudioSegment.silent(duration=150)

        return combined

    def _parse_script(self, script: str) -> list[tuple[str, str]]:
        """Parse script into (speaker, text) tuples."""
        segments = []
        current_speaker = None
        current_text = []

        for line in script.split('\n'):
            line = line.strip()
            if not line:
                continue

            if ':' in line:
                parts = line.split(':', 1)
                potential_speaker = parts[0].strip()

                if len(potential_speaker) < 20 and potential_speaker.replace(' ', '').isalpha():
                    if current_speaker and current_text:
                        segments.append((current_speaker, ' '.join(current_text)))
                        current_text = []

                    current_speaker = potential_speaker
                    if len(parts) > 1 and parts[1].strip():
                        current_text.append(parts[1].strip())
                    continue

            if current_speaker:
                current_text.append(line)

        if current_speaker and current_text:
            segments.append((current_speaker, ' '.join(current_text)))

        return segments
