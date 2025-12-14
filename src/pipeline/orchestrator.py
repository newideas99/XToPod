"""
Main pipeline orchestrator for the Twitter-to-Podcast workflow.

The pipeline runs in two modes:
1. HOURLY: Scrape tweets and store in database
2. DAILY: Analyze tweets, generate script, produce podcast

Architecture:
    HOURLY: Twitter/X (Playwright) → Collection Script → SQLite Database
                                                              │
    DAILY:  Query 24h Data → LLM Summarization → Script Generation → TTS → Audio File
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Optional
import structlog
from pydantic import BaseModel

from ..scrapers import PlaywrightScraper, Tweet
from ..scrapers.playwright_scraper import ScraperConfig
from ..storage import TweetDatabase, TweetRepository, init_database
from ..processors import TweetAnalyzer, PodcastScriptGenerator
from ..processors.analyzer import AnalyzerConfig
from ..processors.script_generator import ScriptConfig, PodcastScript
from ..tts import TTSProvider, GeminiTTS, ElevenLabsTTS, OpenAITTS
from ..tts.gemini_tts import GeminiTTSConfig
from ..tts.elevenlabs_tts import ElevenLabsConfig
from ..tts.openai_tts import OpenAITTSConfig

logger = structlog.get_logger()


class PipelineConfig(BaseModel):
    """Configuration for the entire pipeline."""

    # Database
    db_path: Path = Path("data/xtopod.db")

    # Scraping
    twitter_auth_token: Optional[str] = None
    twitter_ct0_token: Optional[str] = None
    twitter_cookies_file: Optional[Path] = None
    scrape_headless: bool = False
    tweets_per_scrape: int = 100

    # LLM Analysis - Default to OpenRouter with Gemini
    llm_provider: str = "openrouter"  # openrouter, openai, anthropic
    llm_api_key: Optional[str] = None
    analysis_model: str = "google/gemini-2.5-flash-preview-05-20"
    script_model: str = "google/gemini-2.5-flash-preview-05-20"

    # TTS
    tts_provider: str = "gemini"  # gemini, elevenlabs, openai
    tts_api_key: Optional[str] = None
    host1_name: str = "Alex"
    host2_name: str = "Jordan"
    host1_voice: str = "Kore"
    host2_voice: str = "Puck"

    # Podcast settings
    podcast_name: str = "X Digest"
    target_duration_minutes: int = 15
    min_interest_score: float = 6.0
    max_topics: int = 10
    podcast_style: str = "casual"

    # Output
    output_dir: Path = Path("output")

    class Config:
        extra = "allow"


class PodcastPipeline:
    """
    Main orchestrator for the Twitter-to-Podcast pipeline.

    Usage:
        config = PipelineConfig(
            twitter_auth_token="...",
            llm_api_key="...",
            tts_api_key="...",
        )
        pipeline = PodcastPipeline(config)

        # Hourly: collect tweets
        await pipeline.collect_tweets()

        # Daily: generate podcast
        audio_path = await pipeline.generate_podcast()
    """

    def __init__(self, config: PipelineConfig):
        self.config = config
        self.config.output_dir.mkdir(parents=True, exist_ok=True)

        self._db: Optional[TweetDatabase] = None
        self._repo: Optional[TweetRepository] = None

    async def _ensure_db(self) -> TweetRepository:
        """Ensure database connection is established."""
        if self._db is None:
            self._db = await init_database(self.config.db_path)
            self._repo = TweetRepository(self._db)
        return self._repo

    async def collect_tweets(self) -> int:
        """
        Collect tweets from Twitter/X For You feed.
        Run this hourly to build up content for daily podcasts.

        Returns the number of tweets collected.
        """
        logger.info("Starting tweet collection...")

        repo = await self._ensure_db()

        # Set up scraper
        scraper_config = ScraperConfig(
            auth_token=self.config.twitter_auth_token,
            ct0_token=self.config.twitter_ct0_token,
            cookies_file=self.config.twitter_cookies_file,
            headless=self.config.scrape_headless,
            tweets_per_session=self.config.tweets_per_scrape,
        )
        scraper = PlaywrightScraper(scraper_config)

        # Collect tweets
        collected = 0
        async for tweet in scraper.scrape_for_you_feed():
            if await repo.save_tweet(tweet):
                collected += 1

        logger.info(f"Collected {collected} new tweets")
        return collected

    async def analyze_tweets(self, hours: int = 24) -> int:
        """
        Analyze unanalyzed tweets using LLM.
        Run this before generating podcast.

        Returns the number of tweets analyzed.
        """
        logger.info("Starting tweet analysis...")

        repo = await self._ensure_db()

        # Get unanalyzed tweets
        tweets = await repo.get_unanalyzed_tweets(limit=500)
        if not tweets:
            logger.info("No unanalyzed tweets found")
            return 0

        # Set up analyzer - uses OpenRouter by default
        analyzer_config = AnalyzerConfig(
            provider=self.config.llm_provider,
            model=self.config.analysis_model,
            api_key=self.config.llm_api_key,
        )
        analyzer = TweetAnalyzer(analyzer_config)

        # Analyze tweets
        analyses = await analyzer.analyze_tweets(tweets)

        # Update database
        for tweet_id, analysis in analyses.items():
            await repo.update_analysis(
                tweet_id=tweet_id,
                interest_score=analysis.interest_score,
                topics=analysis.topics,
                summary=analysis.reason,
            )

        logger.info(f"Analyzed {len(analyses)} tweets")
        return len(analyses)

    async def generate_podcast(
        self,
        hours: int = 24,
        episode_title: Optional[str] = None,
    ) -> Path:
        """
        Generate a podcast from the day's most interesting tweets.

        This is the main daily task that:
        1. Fetches top-scoring tweets
        2. Generates a podcast script
        3. Converts to audio using TTS

        Returns the path to the generated audio file.
        """
        logger.info("Starting podcast generation...")

        repo = await self._ensure_db()

        # Step 1: Get interesting tweets
        tweets = await repo.get_top_tweets(
            hours=hours,
            limit=self.config.max_topics,
            min_interest_score=self.config.min_interest_score,
        )

        if not tweets:
            logger.warning("No interesting tweets found for podcast")
            raise ValueError("No content available for podcast generation")

        logger.info(f"Selected {len(tweets)} tweets for podcast")

        # Step 2: Generate script
        script = await self._generate_script(tweets)

        # Step 3: Generate audio
        audio_path = await self._generate_audio(script, episode_title)

        # Step 4: Mark tweets as included
        episode_id = audio_path.stem
        await repo.mark_included_in_episode(
            tweet_ids=[t.tweet_id for t in tweets],
            episode_id=episode_id,
        )

        logger.info(f"Podcast generated: {audio_path}")
        return audio_path

    async def _generate_script(self, tweets: list[Tweet]) -> PodcastScript:
        """Generate podcast script from tweets."""
        # Get analyses for these tweets
        repo = await self._ensure_db()

        # Build analyses dict from stored data
        from ..processors.analyzer import TweetAnalysis
        analyses = {}
        for tweet in tweets:
            analyses[tweet.tweet_id] = TweetAnalysis(
                interest_score=tweet.interest_score or 5.0,
                reason=tweet.summary or "",
                topics=tweet.topics,
                talking_points=[],  # Will be generated in script
                sentiment="neutral",
                is_controversial=False,
                has_breaking_news=False,
            )

        # Generate script - uses OpenRouter by default
        script_config = ScriptConfig(
            provider=self.config.llm_provider,
            model=self.config.script_model,
            api_key=self.config.llm_api_key,
            host1_name=self.config.host1_name,
            host2_name=self.config.host2_name,
            podcast_name=self.config.podcast_name,
            target_duration_minutes=self.config.target_duration_minutes,
            style=self.config.podcast_style,
        )
        generator = PodcastScriptGenerator(script_config)

        return await generator.generate_script(tweets, analyses)

    async def _generate_audio(
        self,
        script: PodcastScript,
        episode_title: Optional[str] = None,
    ) -> Path:
        """Generate audio from script using TTS."""
        # Get TTS provider
        tts = self._get_tts_provider()

        # Generate filename
        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        title_slug = (episode_title or script.title).lower().replace(" ", "_")[:30]
        filename = f"{date_str}_{title_slug}.mp3"
        output_path = self.config.output_dir / "audio" / filename

        # Convert script to TTS format and generate
        tts_script = script.to_tts_format()
        return await tts.generate_audio(tts_script, output_path)

    def _get_tts_provider(self) -> TTSProvider:
        """Get configured TTS provider."""
        if self.config.tts_provider == "gemini":
            config = GeminiTTSConfig(
                api_key=self.config.tts_api_key,
                host1_voice=self.config.host1_voice,
                host2_voice=self.config.host2_voice,
                host1_name=self.config.host1_name,
                host2_name=self.config.host2_name,
                output_dir=self.config.output_dir / "audio",
            )
            return GeminiTTS(config)

        elif self.config.tts_provider == "elevenlabs":
            config = ElevenLabsConfig(
                api_key=self.config.tts_api_key,
                host1_voice=self.config.host1_voice,
                host2_voice=self.config.host2_voice,
                host1_name=self.config.host1_name,
                host2_name=self.config.host2_name,
                output_dir=self.config.output_dir / "audio",
            )
            return ElevenLabsTTS(config)

        elif self.config.tts_provider == "openai":
            config = OpenAITTSConfig(
                api_key=self.config.tts_api_key,
                host1_voice=self.config.host1_voice,
                host2_voice=self.config.host2_voice,
                host1_name=self.config.host1_name,
                host2_name=self.config.host2_name,
                output_dir=self.config.output_dir / "audio",
            )
            return OpenAITTS(config)

        else:
            raise ValueError(f"Unknown TTS provider: {self.config.tts_provider}")

    async def run_full_pipeline(self) -> Path:
        """
        Run the complete pipeline: collect, analyze, and generate.
        Useful for testing or manual runs.
        """
        await self.collect_tweets()
        await self.analyze_tweets()
        return await self.generate_podcast()

    async def get_stats(self) -> dict:
        """Get pipeline statistics."""
        repo = await self._ensure_db()
        return await repo.get_stats()

    async def cleanup(self, days: int = 30) -> int:
        """Clean up old tweets. Returns count deleted."""
        repo = await self._ensure_db()
        return await repo.cleanup_old_tweets(days)

    async def close(self):
        """Close database connection."""
        if self._db:
            await self._db.close()
