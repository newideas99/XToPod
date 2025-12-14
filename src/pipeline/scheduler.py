"""
Pipeline scheduler for automated daily podcast generation.

Supports multiple scheduling approaches:
1. APScheduler for simple cron-like scheduling
2. Prefect for more robust orchestration with retries and monitoring
"""

import asyncio
from datetime import datetime, time
from typing import Optional, Callable
import structlog

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .orchestrator import PodcastPipeline, PipelineConfig

logger = structlog.get_logger()


class PipelineScheduler:
    """
    Scheduler for automated podcast generation.

    Usage:
        config = PipelineConfig(...)
        scheduler = PipelineScheduler(config)

        # Start automated scheduling
        await scheduler.start()

        # Or run manually
        await scheduler.run_collection()
        await scheduler.run_generation()
    """

    def __init__(
        self,
        config: PipelineConfig,
        collection_interval_minutes: int = 60,
        generation_hour: int = 6,
        generation_minute: int = 0,
        timezone: str = "UTC",
    ):
        self.config = config
        self.collection_interval = collection_interval_minutes
        self.generation_hour = generation_hour
        self.generation_minute = generation_minute
        self.timezone = timezone

        self.pipeline = PodcastPipeline(config)
        self.scheduler = AsyncIOScheduler(timezone=timezone)

        self._on_collection_complete: Optional[Callable] = None
        self._on_generation_complete: Optional[Callable] = None
        self._on_error: Optional[Callable] = None

    def on_collection_complete(self, callback: Callable):
        """Set callback for when collection completes."""
        self._on_collection_complete = callback

    def on_generation_complete(self, callback: Callable):
        """Set callback for when generation completes."""
        self._on_generation_complete = callback

    def on_error(self, callback: Callable):
        """Set callback for errors."""
        self._on_error = callback

    async def start(self):
        """Start the scheduler with both collection and generation jobs."""
        # Hourly collection job
        self.scheduler.add_job(
            self._run_collection_job,
            IntervalTrigger(minutes=self.collection_interval),
            id="tweet_collection",
            name="Hourly Tweet Collection",
            replace_existing=True,
        )

        # Daily podcast generation job
        self.scheduler.add_job(
            self._run_generation_job,
            CronTrigger(
                hour=self.generation_hour,
                minute=self.generation_minute,
                timezone=self.timezone,
            ),
            id="podcast_generation",
            name="Daily Podcast Generation",
            replace_existing=True,
        )

        # Analysis job (runs before generation)
        self.scheduler.add_job(
            self._run_analysis_job,
            CronTrigger(
                hour=self.generation_hour - 1 if self.generation_hour > 0 else 23,
                minute=self.generation_minute,
                timezone=self.timezone,
            ),
            id="tweet_analysis",
            name="Pre-Generation Tweet Analysis",
            replace_existing=True,
        )

        self.scheduler.start()
        logger.info(
            f"Scheduler started: "
            f"Collection every {self.collection_interval} min, "
            f"Generation at {self.generation_hour:02d}:{self.generation_minute:02d} {self.timezone}"
        )

    def stop(self):
        """Stop the scheduler."""
        self.scheduler.shutdown()
        logger.info("Scheduler stopped")

    async def run_collection(self) -> int:
        """Manually trigger tweet collection."""
        return await self._run_collection_job()

    async def run_analysis(self) -> int:
        """Manually trigger tweet analysis."""
        return await self._run_analysis_job()

    async def run_generation(self) -> str:
        """Manually trigger podcast generation."""
        path = await self._run_generation_job()
        return str(path) if path else ""

    async def _run_collection_job(self) -> int:
        """Internal: Run collection with error handling."""
        logger.info("Starting scheduled tweet collection...")
        try:
            count = await self.pipeline.collect_tweets()
            logger.info(f"Collection complete: {count} tweets")

            if self._on_collection_complete:
                await self._on_collection_complete(count)

            return count

        except Exception as e:
            logger.error(f"Collection failed: {e}")
            if self._on_error:
                await self._on_error("collection", e)
            return 0

    async def _run_analysis_job(self) -> int:
        """Internal: Run analysis with error handling."""
        logger.info("Starting scheduled tweet analysis...")
        try:
            count = await self.pipeline.analyze_tweets()
            logger.info(f"Analysis complete: {count} tweets analyzed")
            return count

        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            if self._on_error:
                await self._on_error("analysis", e)
            return 0

    async def _run_generation_job(self):
        """Internal: Run generation with error handling."""
        logger.info("Starting scheduled podcast generation...")
        try:
            path = await self.pipeline.generate_podcast()
            logger.info(f"Generation complete: {path}")

            if self._on_generation_complete:
                await self._on_generation_complete(str(path))

            return path

        except Exception as e:
            logger.error(f"Generation failed: {e}")
            if self._on_error:
                await self._on_error("generation", e)
            return None

    def get_next_runs(self) -> dict:
        """Get next scheduled run times."""
        jobs = {}
        for job in self.scheduler.get_jobs():
            jobs[job.id] = {
                "name": job.name,
                "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            }
        return jobs

    async def get_stats(self) -> dict:
        """Get pipeline statistics."""
        stats = await self.pipeline.get_stats()
        stats["next_runs"] = self.get_next_runs()
        return stats


# Prefect-based scheduler for more robust orchestration
try:
    from prefect import flow, task
    from prefect.schedules import CronSchedule

    @task(name="collect_tweets", retries=3, retry_delay_seconds=60)
    async def collect_tweets_task(config: dict) -> int:
        """Prefect task for tweet collection."""
        pipeline_config = PipelineConfig(**config)
        pipeline = PodcastPipeline(pipeline_config)
        try:
            return await pipeline.collect_tweets()
        finally:
            await pipeline.close()

    @task(name="analyze_tweets", retries=2, retry_delay_seconds=30)
    async def analyze_tweets_task(config: dict) -> int:
        """Prefect task for tweet analysis."""
        pipeline_config = PipelineConfig(**config)
        pipeline = PodcastPipeline(pipeline_config)
        try:
            return await pipeline.analyze_tweets()
        finally:
            await pipeline.close()

    @task(name="generate_podcast", retries=2, retry_delay_seconds=60)
    async def generate_podcast_task(config: dict) -> str:
        """Prefect task for podcast generation."""
        pipeline_config = PipelineConfig(**config)
        pipeline = PodcastPipeline(pipeline_config)
        try:
            path = await pipeline.generate_podcast()
            return str(path)
        finally:
            await pipeline.close()

    @flow(name="daily_podcast_pipeline")
    async def daily_podcast_flow(config: dict) -> str:
        """
        Prefect flow for daily podcast generation.

        Run with:
            from prefect.schedules import CronSchedule
            daily_podcast_flow.serve(
                schedule=CronSchedule("0 6 * * *"),  # Daily at 6 AM
                parameters={"config": {...}}
            )
        """
        # Run analysis first
        analyzed = await analyze_tweets_task(config)
        logger.info(f"Analyzed {analyzed} tweets")

        # Generate podcast
        audio_path = await generate_podcast_task(config)
        logger.info(f"Generated podcast: {audio_path}")

        return audio_path

    @flow(name="hourly_collection")
    async def hourly_collection_flow(config: dict) -> int:
        """Prefect flow for hourly tweet collection."""
        return await collect_tweets_task(config)

    PREFECT_AVAILABLE = True

except ImportError:
    PREFECT_AVAILABLE = False
    # Silently fall back to APScheduler - Prefect is optional


async def run_scheduler_forever(config: PipelineConfig):
    """Run the scheduler indefinitely."""
    scheduler = PipelineScheduler(config)
    await scheduler.start()

    # Keep running
    try:
        while True:
            await asyncio.sleep(60)
    except KeyboardInterrupt:
        scheduler.stop()
