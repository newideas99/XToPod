"""
LLM-based tweet analysis for identifying interesting content.

Uses OpenRouter for access to multiple models (Gemini, Claude, GPT, etc.)
for cost-effective analysis.
"""

import json
from typing import Optional
from datetime import datetime
import structlog
from pydantic import BaseModel

# LLM client imports - OpenRouter uses OpenAI-compatible API
from openai import AsyncOpenAI

from ..scrapers.models import Tweet

logger = structlog.get_logger()

# OpenRouter base URL
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class TweetAnalysis(BaseModel):
    """Result of LLM analysis for a tweet."""

    interest_score: float  # 1-10
    reason: str
    topics: list[str]
    talking_points: list[str]
    sentiment: str  # positive, negative, neutral, mixed
    is_controversial: bool
    has_breaking_news: bool


class AnalyzerConfig(BaseModel):
    """Configuration for the tweet analyzer."""

    provider: str = "openrouter"  # openrouter (recommended), openai, anthropic
    model: str = "google/gemini-2.5-flash-preview-05-20"  # OpenRouter model ID
    api_key: Optional[str] = None  # OpenRouter API key
    base_url: Optional[str] = None  # Custom base URL (defaults to OpenRouter)

    # Legacy support
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None

    # Analysis parameters
    batch_size: int = 20  # Tweets per API call
    temperature: float = 0.3
    max_tokens: int = 4096


ANALYSIS_PROMPT = """You are a skilled content curator analyzing tweets for a daily podcast.
Your job is to identify the most interesting, newsworthy, and discussion-worthy tweets.

Evaluate each tweet on these criteria:
1. **Novelty** (1-3): Is this new information, announcement, or insight?
2. **Impact** (1-3): Does this affect many people or is it significant?
3. **Engagement potential** (1-2): Would listeners find this interesting to hear discussed?
4. **Discussion value** (1-2): Are there multiple angles or perspectives to explore?

The interest_score is the sum of these (max 10).

Score > 7: Must include - breaking news, major announcements, viral moments
Score 5-7: Strong candidate - interesting discussions, notable opinions
Score 3-5: Maybe include - decent content but not standout
Score < 3: Skip - mundane updates, spam, low-value content

For each tweet, provide:
- interest_score (1-10)
- reason (brief explanation of the score)
- topics (list of 1-3 topic tags)
- talking_points (2-3 specific angles for podcast discussion)
- sentiment (positive/negative/neutral/mixed)
- is_controversial (true if likely to spark debate)
- has_breaking_news (true if this is breaking/new information)

Analyze these tweets and return a JSON array:

{tweets}

Return ONLY valid JSON in this format:
[
  {{
    "tweet_id": "...",
    "interest_score": 7.5,
    "reason": "...",
    "topics": ["tech", "AI"],
    "talking_points": ["...", "..."],
    "sentiment": "positive",
    "is_controversial": false,
    "has_breaking_news": true
  }}
]"""


class TweetAnalyzer:
    """Analyzes tweets using LLMs to identify interesting content."""

    def __init__(self, config: AnalyzerConfig):
        self.config = config

        # Determine API key and base URL
        api_key = config.api_key or config.openai_api_key

        if config.provider == "openrouter":
            self.client = AsyncOpenAI(
                api_key=api_key,
                base_url=config.base_url or OPENROUTER_BASE_URL,
            )
        elif config.provider == "openai":
            self.client = AsyncOpenAI(api_key=api_key)
        else:
            # Default to OpenRouter for any other provider
            self.client = AsyncOpenAI(
                api_key=api_key,
                base_url=config.base_url or OPENROUTER_BASE_URL,
            )

    async def analyze_tweets(self, tweets: list[Tweet]) -> dict[str, TweetAnalysis]:
        """
        Analyze a batch of tweets and return analysis results.

        Returns dict mapping tweet_id to TweetAnalysis.
        """
        if not tweets:
            return {}

        results = {}

        # Process in batches
        for i in range(0, len(tweets), self.config.batch_size):
            batch = tweets[i:i + self.config.batch_size]
            batch_results = await self._analyze_batch(batch)
            results.update(batch_results)
            logger.info(f"Analyzed batch {i // self.config.batch_size + 1}, "
                       f"{len(batch_results)} results")

        return results

    async def _analyze_batch(self, tweets: list[Tweet]) -> dict[str, TweetAnalysis]:
        """Analyze a single batch of tweets."""
        # Format tweets for the prompt
        tweets_text = "\n\n".join([
            f"Tweet ID: {t.tweet_id}\n"
            f"Author: @{t.username} ({t.display_name})\n"
            f"Text: {t.text}\n"
            f"Engagement: {t.likes} likes, {t.retweets} RTs, {t.replies} replies"
            + (f", {t.views} views" if t.views else "")
            for t in tweets
        ])

        prompt = ANALYSIS_PROMPT.format(tweets=tweets_text)

        try:
            response = await self._call_llm(prompt)
            return self._parse_response(response)

        except Exception as e:
            logger.error(f"Failed to analyze batch: {e}")
            return {}

    async def _call_llm(self, prompt: str) -> str:
        """Call LLM via OpenRouter or OpenAI-compatible API."""
        # Build request - OpenRouter is OpenAI-compatible
        request_params = {
            "model": self.config.model,
            "messages": [
                {"role": "system", "content": "You are a content analysis assistant. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }

        # Add JSON mode if supported (works with most models on OpenRouter)
        # Some models may not support it, so we handle gracefully
        try:
            response = await self.client.chat.completions.create(
                **request_params,
                response_format={"type": "json_object"}
            )
        except Exception:
            # Fallback without JSON mode for models that don't support it
            response = await self.client.chat.completions.create(**request_params)

        return response.choices[0].message.content

    def _parse_response(self, response: str) -> dict[str, TweetAnalysis]:
        """Parse LLM response into TweetAnalysis objects."""
        results = {}

        try:
            # Handle both direct array and wrapped object responses
            data = json.loads(response)
            if isinstance(data, dict):
                # OpenAI might wrap in an object
                if "analyses" in data:
                    analyses = data["analyses"]
                elif "results" in data:
                    analyses = data["results"]
                else:
                    analyses = list(data.values())[0] if data else []
            else:
                analyses = data

            for item in analyses:
                tweet_id = item.get("tweet_id")
                if not tweet_id:
                    continue

                results[tweet_id] = TweetAnalysis(
                    interest_score=float(item.get("interest_score", 5)),
                    reason=item.get("reason", ""),
                    topics=item.get("topics", []),
                    talking_points=item.get("talking_points", []),
                    sentiment=item.get("sentiment", "neutral"),
                    is_controversial=item.get("is_controversial", False),
                    has_breaking_news=item.get("has_breaking_news", False),
                )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.debug(f"Response was: {response[:500]}")

        return results

    async def quick_filter(self, tweets: list[Tweet], threshold: float = 5.0) -> list[Tweet]:
        """
        Quick filter to identify potentially interesting tweets before full analysis.
        Uses engagement metrics as a proxy.
        """
        filtered = []
        for tweet in tweets:
            # Skip obvious low-value content
            if len(tweet.text) < 20:
                continue
            if tweet.is_retweet and not tweet.is_quote:
                continue

            # Engagement-based quick score
            engagement_score = (
                tweet.likes * 0.01 +
                tweet.retweets * 0.05 +
                tweet.replies * 0.02
            )

            # Boost for certain patterns
            if any(word in tweet.text.lower() for word in [
                "breaking", "announced", "launch", "released", "first",
                "thread", "🧵", "important", "happening"
            ]):
                engagement_score *= 1.5

            if engagement_score >= threshold or tweet.likes > 1000:
                filtered.append(tweet)

        return filtered
