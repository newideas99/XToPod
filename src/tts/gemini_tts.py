"""
Google Gemini 2.5 TTS Provider.

Gemini 2.5 provides native multi-speaker TTS that can generate NotebookLM-style
dialogue directly. This is the most cost-effective option for high-quality
podcast-style audio.

Available voices: Puck, Charon, Kore, Fenrir, Aoede, Leda, Orus, Zephyr, etc.
Supports 24+ languages.
"""

import base64
import io
import re
import struct
import wave
from datetime import datetime
from pathlib import Path
from typing import Optional
import structlog

from google import genai
from google.genai import types
import imageio_ffmpeg
from pydub import AudioSegment

from .base import TTSProvider, TTSConfig

logger = structlog.get_logger()

# Configure pydub to use bundled ffmpeg
AudioSegment.converter = imageio_ffmpeg.get_ffmpeg_exe()


def pcm_to_mp3(pcm_data: bytes, sample_rate: int = 24000, channels: int = 1, sample_width: int = 2) -> bytes:
    """Convert raw PCM audio data to MP3 format."""
    # Create AudioSegment from raw PCM data
    audio = AudioSegment(
        data=pcm_data,
        sample_width=sample_width,
        frame_rate=sample_rate,
        channels=channels
    )

    # Export to MP3
    mp3_buffer = io.BytesIO()
    audio.export(mp3_buffer, format="mp3", bitrate="192k")
    return mp3_buffer.getvalue()


class GeminiTTSConfig(TTSConfig):
    """Configuration for Gemini TTS."""

    api_key: str
    model: str = "gemini-2.5-flash-preview-tts"

    # Available voices: Puck, Charon, Kore, Fenrir, Aoede, Leda, Orus, Zephyr
    host1_voice: str = "Kore"  # Female voice
    host2_voice: str = "Puck"  # Male voice


class GeminiTTS(TTSProvider):
    """
    Gemini 2.5 TTS provider with native multi-speaker support.

    This is the recommended provider for NotebookLM-style podcasts as it:
    - Natively supports 2-speaker dialogue
    - Produces natural conversational audio
    - Is cost-effective (~$6-12/month for daily 30-min podcasts)
    """

    def __init__(self, config: GeminiTTSConfig):
        super().__init__(config)
        self.config: GeminiTTSConfig = config
        self.client = genai.Client(api_key=config.api_key)

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def supports_multi_speaker(self) -> bool:
        return True

    async def generate_audio(
        self,
        script: str,
        output_path: Optional[Path] = None,
    ) -> Path:
        """
        Generate multi-speaker audio from a dialogue script.

        Script format:
        Speaker1: Hello, welcome to the show!
        Speaker2: Thanks for having me!

        The speaker names in the script will be mapped to the configured voices.
        """
        if output_path is None:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            output_path = self.config.output_dir / f"podcast_{timestamp}.{self.config.output_format}"

        # Parse the script to extract speaker names
        speakers = self._extract_speakers(script)
        if len(speakers) < 2:
            logger.warning("Script has fewer than 2 speakers, using single-speaker mode")
            return await self.generate_single_speaker(script, self.config.host1_voice, output_path)

        # Build speaker configuration
        speaker_configs = []
        for i, speaker in enumerate(speakers[:2]):  # Gemini supports up to 2 speakers
            voice = self.config.host1_voice if i == 0 else self.config.host2_voice
            speaker_configs.append(
                types.SpeakerVoiceConfig(
                    speaker=speaker,
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voice
                        )
                    )
                )
            )

        logger.info(f"Generating multi-speaker audio with Gemini 2.5 TTS")
        logger.info(f"Speakers: {speakers[:2]} -> Voices: {self.config.host1_voice}, {self.config.host2_voice}")

        try:
            response = self.client.models.generate_content(
                model=self.config.model,
                contents=script,
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                            speaker_voice_configs=speaker_configs
                        )
                    )
                )
            )

            # Extract audio data from response
            audio_data = None
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'inline_data') and part.inline_data:
                    if part.inline_data.mime_type.startswith('audio/'):
                        audio_data = part.inline_data.data
                        break

            if audio_data is None:
                raise ValueError("No audio data in Gemini response")

            # Decode audio data
            if isinstance(audio_data, str):
                audio_bytes = base64.b64decode(audio_data)
            else:
                audio_bytes = audio_data

            # Convert raw PCM to MP3 format (Gemini returns raw PCM)
            mp3_bytes = pcm_to_mp3(audio_bytes, sample_rate=self.config.sample_rate)

            # Save as MP3
            output_path = output_path.with_suffix('.mp3')
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                f.write(mp3_bytes)

            logger.info(f"Audio saved to {output_path} ({len(mp3_bytes) / 1024 / 1024:.1f} MB)")
            return output_path

        except Exception as e:
            logger.error(f"Gemini TTS generation failed: {e}")
            raise

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

        response = self.client.models.generate_content(
            model=self.config.model,
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=voice
                        )
                    )
                )
            )
        )

        audio_data = None
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'inline_data') and part.inline_data:
                if part.inline_data.mime_type.startswith('audio/'):
                    audio_data = part.inline_data.data
                    break

        if audio_data is None:
            raise ValueError("No audio data in Gemini response")

        if isinstance(audio_data, str):
            audio_bytes = base64.b64decode(audio_data)
        else:
            audio_bytes = audio_data

        # Convert raw PCM to MP3 format
        mp3_bytes = pcm_to_mp3(audio_bytes, sample_rate=self.config.sample_rate)

        output_path = output_path.with_suffix('.mp3')
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(mp3_bytes)

        return output_path

    def _extract_speakers(self, script: str) -> list[str]:
        """Extract unique speaker names from the script."""
        # Match patterns like "Speaker:" or "Name:"
        pattern = r'^([A-Za-z]+):'
        speakers = []
        for line in script.split('\n'):
            match = re.match(pattern, line.strip())
            if match:
                speaker = match.group(1)
                if speaker not in speakers:
                    speakers.append(speaker)
        return speakers

    async def generate_with_style(
        self,
        script: str,
        style_prompt: str,
        output_path: Optional[Path] = None,
    ) -> Path:
        """
        Generate audio with additional style control.

        Gemini TTS supports natural language style prompts like:
        - "Speak in an excited, energetic tone"
        - "Use a calm, thoughtful delivery"
        - "Add enthusiasm when discussing new features"
        """
        # Prepend style instructions to the script
        styled_script = f"[Style: {style_prompt}]\n\n{script}"
        return await self.generate_audio(styled_script, output_path)
