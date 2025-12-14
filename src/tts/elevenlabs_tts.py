"""
ElevenLabs TTS Provider.

ElevenLabs offers the highest quality TTS with:
- 3000+ voices
- Voice cloning from short samples
- 82% pronunciation accuracy
- Natural emotional delivery

Cost: $99-330/month for daily 15-30 minute podcasts
"""

from datetime import datetime
from pathlib import Path
from typing import Optional
import structlog
import asyncio
from io import BytesIO

from elevenlabs import AsyncElevenLabs, VoiceSettings

from .base import TTSProvider, TTSConfig

logger = structlog.get_logger()


class ElevenLabsConfig(TTSConfig):
    """Configuration for ElevenLabs TTS."""

    api_key: str
    model: str = "eleven_multilingual_v2"

    # Voice IDs - can use names or IDs
    # Popular voices: "Rachel", "Adam", "Domi", "Elli", "Josh", "Arnold"
    host1_voice: str = "Rachel"
    host2_voice: str = "Adam"

    # Voice settings
    stability: float = 0.5
    similarity_boost: float = 0.75
    style: float = 0.0
    use_speaker_boost: bool = True


class ElevenLabsTTS(TTSProvider):
    """
    ElevenLabs TTS provider.

    Premium quality TTS with the most natural emotional delivery.
    Does not natively support multi-speaker in one call - we generate
    segments separately and combine them.
    """

    def __init__(self, config: ElevenLabsConfig):
        super().__init__(config)
        self.config: ElevenLabsConfig = config
        self.client = AsyncElevenLabs(api_key=config.api_key)

        self.voice_settings = VoiceSettings(
            stability=config.stability,
            similarity_boost=config.similarity_boost,
            style=config.style,
            use_speaker_boost=config.use_speaker_boost,
        )

    @property
    def name(self) -> str:
        return "elevenlabs"

    @property
    def supports_multi_speaker(self) -> bool:
        return False  # Need to generate per-speaker and combine

    async def generate_audio(
        self,
        script: str,
        output_path: Optional[Path] = None,
    ) -> Path:
        """
        Generate audio from a multi-speaker script.

        Since ElevenLabs doesn't support multi-speaker natively,
        we parse the script, generate each segment, and combine them.
        """
        if output_path is None:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            output_path = self.config.output_dir / f"podcast_{timestamp}.{self.config.output_format}"

        # Parse script into segments
        segments = self._parse_script(script)

        if not segments:
            raise ValueError("No dialogue segments found in script")

        logger.info(f"Generating {len(segments)} audio segments with ElevenLabs")

        # Generate audio for each segment
        audio_segments = []
        for i, (speaker, text) in enumerate(segments):
            voice = self.config.host1_voice if speaker == self.config.host1_name else self.config.host2_voice
            logger.debug(f"Segment {i + 1}/{len(segments)}: {speaker} ({voice})")

            segment_audio = await self._generate_segment(text, voice)
            audio_segments.append(segment_audio)

            # Small delay to avoid rate limits
            await asyncio.sleep(0.1)

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
        audio_generator = await self.client.text_to_speech.convert(
            voice_id=voice,
            text=text,
            model_id=self.config.model,
            voice_settings=self.voice_settings,
        )

        # Collect all chunks
        audio_bytes = b""
        async for chunk in audio_generator:
            audio_bytes += chunk

        return audio_bytes

    async def _combine_segments(self, segments: list[bytes]):
        """Combine audio segments using pydub."""
        from pydub import AudioSegment

        combined = AudioSegment.empty()

        for segment_bytes in segments:
            # Load segment
            segment = AudioSegment.from_mp3(BytesIO(segment_bytes))
            # Add small pause between speakers
            combined += segment + AudioSegment.silent(duration=200)

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

            # Check if line starts with a speaker name
            if ':' in line:
                parts = line.split(':', 1)
                potential_speaker = parts[0].strip()

                # If it looks like a speaker name (short, alphabetic)
                if len(potential_speaker) < 20 and potential_speaker.replace(' ', '').isalpha():
                    # Save previous segment
                    if current_speaker and current_text:
                        segments.append((current_speaker, ' '.join(current_text)))
                        current_text = []

                    current_speaker = potential_speaker
                    if len(parts) > 1 and parts[1].strip():
                        current_text.append(parts[1].strip())
                    continue

            # Add line to current segment
            if current_speaker:
                current_text.append(line)

        # Save last segment
        if current_speaker and current_text:
            segments.append((current_speaker, ' '.join(current_text)))

        return segments

    async def list_voices(self) -> list[dict]:
        """List available voices."""
        response = await self.client.voices.get_all()
        return [
            {
                "voice_id": v.voice_id,
                "name": v.name,
                "category": v.category,
                "description": v.description,
            }
            for v in response.voices
        ]
