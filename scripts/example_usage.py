#!/usr/bin/env python3
"""
Example usage of Xtopod for generating a podcast from Twitter.

This script demonstrates the programmatic API for more customized usage.
"""

import asyncio
import os
from pathlib import Path

# Add src to path for direct execution
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dotenv import load_dotenv

# Load environment variables
load_dotenv()


async def example_collect_and_analyze():
    """Example: Collect tweets and analyze them."""
    from pipeline import PodcastPipeline, PipelineConfig

    config = PipelineConfig(
        twitter_auth_token=os.getenv("TWITTER_AUTH_TOKEN"),
        twitter_ct0_token=os.getenv("TWITTER_CT0_TOKEN"),
        llm_api_key=os.getenv("OPENAI_API_KEY"),
        tweets_per_scrape=50,  # Collect 50 tweets
    )

    pipeline = PodcastPipeline(config)

    try:
        # Collect tweets
        print("Collecting tweets...")
        collected = await pipeline.collect_tweets()
        print(f"Collected {collected} tweets")

        # Analyze them
        print("Analyzing tweets...")
        analyzed = await pipeline.analyze_tweets()
        print(f"Analyzed {analyzed} tweets")

        # Show stats
        stats = await pipeline.get_stats()
        print(f"\nDatabase stats:")
        for key, value in stats.items():
            print(f"  {key}: {value}")

    finally:
        await pipeline.close()


async def example_generate_podcast():
    """Example: Generate a podcast from already-collected tweets."""
    from pipeline import PodcastPipeline, PipelineConfig

    config = PipelineConfig(
        llm_provider="openai",
        llm_api_key=os.getenv("OPENAI_API_KEY"),
        tts_provider="gemini",
        tts_api_key=os.getenv("GOOGLE_API_KEY"),
        podcast_name="My Twitter Digest",
        host1_name="Sam",
        host2_name="Alex",
        target_duration_minutes=10,
        min_interest_score=5.0,  # Lower threshold for more content
    )

    pipeline = PodcastPipeline(config)

    try:
        print("Generating podcast...")
        audio_path = await pipeline.generate_podcast(
            hours=24,
            episode_title="Today's Twitter Highlights"
        )
        print(f"Podcast saved to: {audio_path}")

    except ValueError as e:
        print(f"Error: {e}")
        print("Make sure you have collected and analyzed tweets first!")

    finally:
        await pipeline.close()


async def example_custom_script_generation():
    """Example: Generate a script without audio (for review/editing)."""
    from processors import TweetAnalyzer, PodcastScriptGenerator
    from processors.analyzer import AnalyzerConfig, TweetAnalysis
    from processors.script_generator import ScriptConfig
    from scrapers.models import Tweet

    # Create some sample tweets (in real usage, these come from the database)
    sample_tweets = [
        Tweet(
            tweet_id="1",
            user_id="user1",
            username="techguru",
            display_name="Tech Guru",
            text="Just announced: Python 4.0 will include native async/await at the language level! 🐍",
            likes=5000,
            retweets=2000,
            replies=500,
        ),
        Tweet(
            tweet_id="2",
            user_id="user2",
            username="ainews",
            display_name="AI News Daily",
            text="OpenAI releases GPT-5 with multimodal reasoning. Early benchmarks show 50% improvement over GPT-4.",
            likes=10000,
            retweets=5000,
            replies=1000,
        ),
    ]

    # Create sample analyses
    analyses = {
        "1": TweetAnalysis(
            interest_score=8.5,
            reason="Major language announcement",
            topics=["python", "programming"],
            talking_points=["Language evolution", "Impact on developers"],
            sentiment="positive",
            is_controversial=False,
            has_breaking_news=True,
        ),
        "2": TweetAnalysis(
            interest_score=9.0,
            reason="Major AI announcement",
            topics=["AI", "OpenAI", "GPT"],
            talking_points=["Capabilities", "Industry impact"],
            sentiment="positive",
            is_controversial=False,
            has_breaking_news=True,
        ),
    }

    # Generate script
    script_config = ScriptConfig(
        provider="openai",
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        host1_name="Emma",
        host2_name="James",
        podcast_name="Tech Talk Daily",
        target_duration_minutes=5,
        style="casual",
    )

    generator = PodcastScriptGenerator(script_config)
    script = await generator.generate_script(sample_tweets, analyses)

    print("Generated Script:")
    print("=" * 50)
    print(f"Title: {script.title}")
    print(f"Description: {script.description}")
    print(f"Topics: {', '.join(script.topics_covered)}")
    print(f"Estimated duration: {generator.estimate_duration(script):.1f} minutes")
    print("=" * 50)
    print("\nDialogue:")
    for line in script.dialogue[:10]:  # First 10 lines
        print(f"{line.speaker}: {line.text}")


async def example_tts_only():
    """Example: Generate audio from a pre-written script."""
    from tts import GeminiTTS
    from tts.gemini_tts import GeminiTTSConfig
    from pathlib import Path

    config = GeminiTTSConfig(
        api_key=os.getenv("GOOGLE_API_KEY"),
        host1_voice="Kore",
        host2_voice="Puck",
        host1_name="Alice",
        host2_name="Bob",
        output_dir=Path("output/audio"),
    )

    tts = GeminiTTS(config)

    # Sample script in multi-speaker format
    script = """
Alice: Welcome back to Tech Talk! Today we have some exciting news about AI.

Bob: That's right, Alice. Let's dive into the biggest stories.

Alice: First up, OpenAI has announced GPT-5. Early benchmarks are impressive.

Bob: Wow, 50% improvement? That's significant. What are the main capabilities?

Alice: They're highlighting multimodal reasoning - the ability to seamlessly combine text, images, and audio understanding.

Bob: Interesting. This could change how we interact with AI assistants.

Alice: Exactly. And that's all for today's quick update. Thanks for listening!

Bob: See you next time!
"""

    print("Generating audio...")
    audio_path = await tts.generate_audio(
        script,
        output_path=Path("output/audio/test_episode.mp3")
    )
    print(f"Audio saved to: {audio_path}")


async def main():
    """Run examples."""
    print("Xtopod Usage Examples")
    print("=" * 50)

    # Uncomment the example you want to run:

    # Example 1: Collect and analyze tweets
    # await example_collect_and_analyze()

    # Example 2: Generate podcast from analyzed tweets
    # await example_generate_podcast()

    # Example 3: Custom script generation (no audio)
    await example_custom_script_generation()

    # Example 4: TTS only (from pre-written script)
    # await example_tts_only()


if __name__ == "__main__":
    asyncio.run(main())
