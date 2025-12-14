"""
Command-line interface for Xtopod.

Usage:
    xtopod collect       # Collect tweets from For You feed
    xtopod analyze       # Analyze collected tweets
    xtopod generate      # Generate today's podcast
    xtopod run           # Run full pipeline once
    xtopod serve         # Start automated scheduler
    xtopod stats         # Show statistics
"""

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from .pipeline import PodcastPipeline, PipelineConfig, PipelineScheduler

app = typer.Typer(
    name="xtopod",
    help="Automated Twitter/X to Podcast Pipeline",
    add_completion=False,
)
console = Console()


def load_config() -> PipelineConfig:
    """Load configuration from environment and .env file."""
    import os
    from dotenv import load_dotenv

    load_dotenv()

    # Get the Gemini model from env, with fallback
    gemini_model = os.getenv("GEMINI_MODEL", "google/gemini-2.5-flash-preview-05-20")

    return PipelineConfig(
        # Database
        db_path=Path(os.getenv("XTOPOD_DB_PATH", "data/xtopod.db")),

        # Twitter
        twitter_auth_token=os.getenv("TWITTER_AUTH_TOKEN"),
        twitter_ct0_token=os.getenv("TWITTER_CT0_TOKEN"),
        twitter_cookies_file=Path(os.getenv("TWITTER_COOKIES_FILE")) if os.getenv("TWITTER_COOKIES_FILE") else None,
        scrape_headless=os.getenv("SCRAPE_HEADLESS", "false").lower() == "true",
        tweets_per_scrape=int(os.getenv("TWEETS_PER_SCRAPE", "100")),

        # LLM - Default to OpenRouter
        llm_provider=os.getenv("LLM_PROVIDER", "openrouter"),
        llm_api_key=os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY"),
        analysis_model=os.getenv("ANALYSIS_MODEL", gemini_model),
        script_model=os.getenv("SCRIPT_MODEL", gemini_model),

        # TTS
        tts_provider=os.getenv("TTS_PROVIDER", "gemini"),
        tts_api_key=os.getenv("GOOGLE_API_KEY") or os.getenv("ELEVENLABS_API_KEY") or os.getenv("OPENAI_API_KEY"),
        host1_name=os.getenv("HOST1_NAME", "Alex"),
        host2_name=os.getenv("HOST2_NAME", "Jordan"),
        host1_voice=os.getenv("HOST1_VOICE", "Kore"),
        host2_voice=os.getenv("HOST2_VOICE", "Puck"),

        # Podcast
        podcast_name=os.getenv("PODCAST_NAME", "Twitter Pulse"),
        target_duration_minutes=int(os.getenv("TARGET_DURATION", "15")),
        min_interest_score=float(os.getenv("MIN_INTEREST_SCORE", "6.0")),
        max_topics=int(os.getenv("MAX_TOPICS", "10")),
        podcast_style=os.getenv("PODCAST_STYLE", "casual"),

        # Output
        output_dir=Path(os.getenv("OUTPUT_DIR", "output")),
    )


@app.command()
def collect(
    count: int = typer.Option(100, "--count", "-n", help="Number of tweets to collect"),
):
    """Collect tweets from your Twitter/X For You feed."""

    async def _collect():
        config = load_config()
        config.tweets_per_scrape = count

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Collecting tweets...", total=None)

            pipeline = PodcastPipeline(config)
            try:
                collected = await pipeline.collect_tweets()
                progress.update(task, completed=True)
                console.print(f"[green]✓[/green] Collected {collected} tweets")
            finally:
                await pipeline.close()

    asyncio.run(_collect())


@app.command()
def analyze(
    hours: int = typer.Option(24, "--hours", "-h", help="Analyze tweets from last N hours"),
):
    """Analyze collected tweets using LLM."""

    async def _analyze():
        config = load_config()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Analyzing tweets...", total=None)

            pipeline = PodcastPipeline(config)
            try:
                analyzed = await pipeline.analyze_tweets(hours=hours)
                progress.update(task, completed=True)
                console.print(f"[green]✓[/green] Analyzed {analyzed} tweets")
            finally:
                await pipeline.close()

    asyncio.run(_analyze())


@app.command()
def generate(
    title: Optional[str] = typer.Option(None, "--title", "-t", help="Episode title"),
    hours: int = typer.Option(24, "--hours", "-h", help="Include tweets from last N hours"),
):
    """Generate a podcast episode from analyzed tweets."""

    async def _generate():
        config = load_config()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Generating podcast...", total=None)

            pipeline = PodcastPipeline(config)
            try:
                audio_path = await pipeline.generate_podcast(hours=hours, episode_title=title)
                progress.update(task, completed=True)
                console.print(f"[green]✓[/green] Podcast generated: {audio_path}")
            except ValueError as e:
                console.print(f"[red]✗[/red] {e}")
            finally:
                await pipeline.close()

    asyncio.run(_generate())


@app.command()
def quick(
    tweets: int = typer.Option(200, "--tweets", "-n", help="Number of tweets to collect"),
    open_folder: bool = typer.Option(True, "--open/--no-open", help="Open output folder when done"),
):
    """Quick mode: scrape tweets and generate podcast immediately.

    This is the fastest way to generate a podcast - collects fresh tweets,
    analyzes them, and generates audio all in one go.
    """
    import subprocess
    import sys

    async def _quick():
        config = load_config()
        config.tweets_per_scrape = tweets

        console.print("[bold]Quick Mode: Generating podcast from fresh tweets[/bold]\n")

        pipeline = PodcastPipeline(config)
        try:
            # Step 1: Collect
            console.print("[cyan][1/3][/cyan] Collecting tweets from your For You feed...")
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
                transient=True,
            ) as progress:
                task = progress.add_task("Scrolling feed...", total=None)
                collected = await pipeline.collect_tweets()
            console.print(f"      [green]✓[/green] Collected {collected} tweets\n")

            if collected == 0:
                console.print("[red]✗[/red] No tweets collected. Check your cookies.json file.")
                return

            # Step 2: Analyze
            console.print("[cyan][2/3][/cyan] Analyzing tweets with AI...")
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
                transient=True,
            ) as progress:
                task = progress.add_task("Processing with Gemini...", total=None)
                analyzed = await pipeline.analyze_tweets()
            console.print(f"      [green]✓[/green] Analyzed {analyzed} tweets\n")

            # Step 3: Generate podcast (use all available tweets, not just last 24h)
            console.print("[cyan][3/3][/cyan] Generating podcast...")
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
                transient=True,
            ) as progress:
                task = progress.add_task("Creating script and audio...", total=None)
                audio_path = await pipeline.generate_podcast(hours=9999)  # Get all tweets
            console.print(f"      [green]✓[/green] Podcast saved to: {audio_path}\n")

            console.print("[bold green]Done![/bold green] Your podcast is ready.")

            # Open output folder
            if open_folder:
                folder = audio_path.parent
                if sys.platform == "darwin":
                    subprocess.run(["open", str(folder)], check=False)
                elif sys.platform == "win32":
                    subprocess.run(["explorer", str(folder)], check=False)
                else:
                    subprocess.run(["xdg-open", str(folder)], check=False)

        except Exception as e:
            console.print(f"[red]✗[/red] Failed: {e}")
            raise
        finally:
            await pipeline.close()

    asyncio.run(_quick())


@app.command()
def run():
    """Run the full pipeline: collect, analyze, and generate.

    Similar to 'quick' but uses time-based filtering (last 24 hours).
    """

    async def _run():
        config = load_config()

        console.print("[bold]Running full pipeline...[/bold]")

        pipeline = PodcastPipeline(config)
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                # Collect
                task = progress.add_task("Collecting tweets...", total=None)
                collected = await pipeline.collect_tweets()
                progress.update(task, description=f"Collected {collected} tweets")

                # Analyze
                task = progress.add_task("Analyzing tweets...", total=None)
                analyzed = await pipeline.analyze_tweets()
                progress.update(task, description=f"Analyzed {analyzed} tweets")

                # Generate
                task = progress.add_task("Generating podcast...", total=None)
                audio_path = await pipeline.generate_podcast()
                progress.update(task, description=f"Generated: {audio_path}")

            console.print(f"\n[green]✓[/green] Pipeline complete!")
            console.print(f"[bold]Output:[/bold] {audio_path}")

        except Exception as e:
            console.print(f"[red]✗[/red] Pipeline failed: {e}")
        finally:
            await pipeline.close()

    asyncio.run(_run())


@app.command()
def serve(
    collection_interval: int = typer.Option(60, "--interval", "-i", help="Collection interval in minutes"),
    generation_hour: int = typer.Option(6, "--hour", help="Hour to generate podcast (0-23)"),
):
    """Start the automated scheduler for continuous podcast generation."""

    async def _serve():
        config = load_config()

        scheduler = PipelineScheduler(
            config,
            collection_interval_minutes=collection_interval,
            generation_hour=generation_hour,
        )

        console.print("[bold]Starting Xtopod scheduler...[/bold]")
        console.print(f"  Collection: every {collection_interval} minutes")
        console.print(f"  Generation: daily at {generation_hour:02d}:00 UTC")
        console.print("\nPress Ctrl+C to stop\n")

        await scheduler.start()

        try:
            while True:
                await asyncio.sleep(60)
        except KeyboardInterrupt:
            scheduler.stop()
            console.print("\n[yellow]Scheduler stopped[/yellow]")

    asyncio.run(_serve())


@app.command()
def stats():
    """Show pipeline statistics."""

    async def _stats():
        config = load_config()
        pipeline = PodcastPipeline(config)

        try:
            stats = await pipeline.get_stats()

            table = Table(title="Xtopod Statistics")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", style="green")

            table.add_row("Total tweets", str(stats.get("total_tweets", 0)))
            table.add_row("Tweets today", str(stats.get("tweets_today", 0)))
            table.add_row("Analyzed tweets", str(stats.get("analyzed_tweets", 0)))
            table.add_row("Avg interest score", str(stats.get("avg_interest_score", 0)))

            console.print(table)

        finally:
            await pipeline.close()

    asyncio.run(_stats())


@app.command()
def cleanup(
    days: int = typer.Option(30, "--days", "-d", help="Delete tweets older than N days"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be deleted"),
):
    """Clean up old tweets from the database."""

    async def _cleanup():
        config = load_config()
        pipeline = PodcastPipeline(config)

        try:
            if dry_run:
                console.print(f"[yellow]Dry run:[/yellow] Would delete tweets older than {days} days")
            else:
                deleted = await pipeline.cleanup(days=days)
                console.print(f"[green]✓[/green] Deleted {deleted} old tweets")
        finally:
            await pipeline.close()

    asyncio.run(_cleanup())


@app.command()
def init():
    """Initialize the project with example configuration."""
    from pathlib import Path

    # Create directories
    dirs = ["data", "output/audio", "output/transcripts", "config"]
    for d in dirs:
        Path(d).mkdir(parents=True, exist_ok=True)
        console.print(f"[green]✓[/green] Created {d}/")

    # Create example .env
    env_example = """# Xtopod Configuration
# Copy to .env and fill in your values

# Twitter/X Authentication (get from browser cookies)
TWITTER_AUTH_TOKEN=
TWITTER_CT0_TOKEN=

# LLM Provider (openai or anthropic)
LLM_PROVIDER=openai
OPENAI_API_KEY=
# ANTHROPIC_API_KEY=

# Analysis models
ANALYSIS_MODEL=gpt-4o-mini
SCRIPT_MODEL=gpt-4o

# TTS Provider (gemini, elevenlabs, or openai)
TTS_PROVIDER=gemini
GOOGLE_API_KEY=
# ELEVENLABS_API_KEY=

# Podcast Settings
PODCAST_NAME=Twitter Pulse
HOST1_NAME=Alex
HOST2_NAME=Jordan
HOST1_VOICE=Kore
HOST2_VOICE=Puck
TARGET_DURATION=15
MIN_INTEREST_SCORE=6.0
PODCAST_STYLE=casual
"""

    env_path = Path(".env.example")
    if not env_path.exists():
        env_path.write_text(env_example)
        console.print(f"[green]✓[/green] Created .env.example")
    else:
        console.print(f"[yellow]![/yellow] .env.example already exists")

    console.print("\n[bold]Setup complete![/bold]")
    console.print("1. Copy .env.example to .env")
    console.print("2. Fill in your API keys")
    console.print("3. Run: xtopod collect")


if __name__ == "__main__":
    app()
