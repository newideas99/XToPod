"""
Configuration settings for Xtopod - Twitter to Podcast pipeline.
Uses pydantic-settings for environment variable management.
"""
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class TwitterSettings(BaseSettings):
    """Twitter/X scraping configuration."""

    model_config = SettingsConfigDict(env_prefix="TWITTER_")

    # Authentication (choose one method)
    auth_token: SecretStr | None = Field(default=None, description="Twitter auth_token cookie")
    ct0_token: SecretStr | None = Field(default=None, description="Twitter ct0 cookie (CSRF)")
    cookies_file: Path | None = Field(default=None, description="Path to cookies.json file")

    # Scraping settings
    scrape_interval_minutes: int = Field(default=60, ge=5, le=1440)
    tweets_per_scrape: int = Field(default=100, ge=10, le=500)
    include_replies: bool = Field(default=False)
    include_retweets: bool = Field(default=True)

    # Anti-detection
    use_proxy: bool = Field(default=False)
    proxy_url: str | None = Field(default=None)
    headless: bool = Field(default=False, description="Headless mode risks detection")
    random_delay_range: tuple[float, float] = Field(default=(1.0, 3.0))


class LLMSettings(BaseSettings):
    """LLM API configuration for summarization and script generation."""

    model_config = SettingsConfigDict(env_prefix="LLM_")

    # Provider selection
    provider: Literal["openai", "anthropic", "google"] = Field(default="openai")

    # API Keys
    openai_api_key: SecretStr | None = Field(default=None)
    anthropic_api_key: SecretStr | None = Field(default=None)
    google_api_key: SecretStr | None = Field(default=None)

    # Model selection
    summarization_model: str = Field(
        default="gpt-4o-mini",
        description="Model for tweet analysis/summarization (use cheaper models)",
    )
    script_model: str = Field(
        default="gpt-4o",
        description="Model for final script generation (quality matters here)",
    )

    # Generation parameters
    max_tokens_summary: int = Field(default=4096)
    max_tokens_script: int = Field(default=8192)
    temperature_summary: float = Field(default=0.3)
    temperature_script: float = Field(default=0.7)


class TTSSettings(BaseSettings):
    """Text-to-Speech configuration."""

    model_config = SettingsConfigDict(env_prefix="TTS_")

    # Provider selection
    provider: Literal["gemini", "elevenlabs", "openai", "dia"] = Field(default="gemini")

    # API Keys
    elevenlabs_api_key: SecretStr | None = Field(default=None)
    google_api_key: SecretStr | None = Field(default=None)  # For Gemini TTS
    openai_api_key: SecretStr | None = Field(default=None)

    # Voice configuration
    host1_voice: str = Field(default="Kore", description="Primary host voice")
    host2_voice: str = Field(default="Puck", description="Secondary host voice")
    host1_name: str = Field(default="Alex")
    host2_name: str = Field(default="Jordan")

    # Audio settings
    output_format: Literal["mp3", "wav", "ogg"] = Field(default="mp3")
    sample_rate: int = Field(default=24000)
    bitrate: str = Field(default="192k")


class PodcastSettings(BaseSettings):
    """Podcast generation configuration."""

    model_config = SettingsConfigDict(env_prefix="PODCAST_")

    # Content settings
    target_duration_minutes: int = Field(default=15, ge=2, le=60)
    style: Literal["casual", "professional", "educational", "entertaining"] = Field(
        default="casual"
    )
    include_intro: bool = Field(default=True)
    include_outro: bool = Field(default=True)

    # Topic filtering
    min_interest_score: int = Field(default=6, ge=1, le=10)
    max_topics_per_episode: int = Field(default=10)

    # Scheduling
    generation_hour: int = Field(default=6, ge=0, le=23, description="Hour to generate podcast")
    timezone: str = Field(default="UTC")


class StorageSettings(BaseSettings):
    """Database and file storage configuration."""

    model_config = SettingsConfigDict(env_prefix="STORAGE_")

    # Database
    db_path: Path = Field(default=Path("data/xtopod.db"))

    # Output directories
    output_dir: Path = Field(default=Path("output"))
    audio_dir: Path = Field(default=Path("output/audio"))
    transcripts_dir: Path = Field(default=Path("output/transcripts"))

    # Retention
    keep_tweets_days: int = Field(default=30)
    keep_audio_days: int = Field(default=90)


class Settings(BaseSettings):
    """Main configuration aggregating all settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Sub-configurations
    twitter: TwitterSettings = Field(default_factory=TwitterSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    tts: TTSSettings = Field(default_factory=TTSSettings)
    podcast: PodcastSettings = Field(default_factory=PodcastSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)

    # Application settings
    debug: bool = Field(default=False)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")


# Global settings instance
settings = Settings()
