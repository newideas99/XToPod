"""
Podcast script generator using LLMs.

Generates natural two-host dialogue scripts from analyzed tweets,
designed to be converted to speech via TTS.

Uses OpenRouter for access to multiple models.
"""

import json
from typing import Optional
from datetime import datetime
import structlog
from pydantic import BaseModel

from openai import AsyncOpenAI

from ..scrapers.models import Tweet
from .analyzer import TweetAnalysis, OPENROUTER_BASE_URL

logger = structlog.get_logger()


class ScriptConfig(BaseModel):
    """Configuration for script generation."""

    provider: str = "openrouter"  # openrouter (recommended), openai
    model: str = "google/gemini-2.5-flash-preview-05-20"  # OpenRouter model ID
    api_key: Optional[str] = None  # OpenRouter API key
    base_url: Optional[str] = None  # Custom base URL

    # Legacy support
    openai_api_key: Optional[str] = None
    anthropic_api_key: Optional[str] = None

    # Podcast parameters
    host1_name: str = "Alex"
    host2_name: str = "Jordan"
    podcast_name: str = "X Digest"
    target_duration_minutes: int = 15
    style: str = "casual"  # casual, professional, educational, entertaining

    temperature: float = 0.7
    max_tokens: int = 8192


class DialogueLine(BaseModel):
    """A single line of dialogue in the podcast script."""

    speaker: str
    text: str
    emotion: Optional[str] = None  # For TTS emotion hints
    is_intro: bool = False
    is_outro: bool = False


class PodcastScript(BaseModel):
    """Complete podcast script with metadata."""

    title: str
    description: str
    generated_at: datetime
    target_duration_minutes: int
    dialogue: list[DialogueLine]
    source_tweet_ids: list[str]
    topics_covered: list[str]

    def to_tts_format(self) -> str:
        """Convert to format suitable for TTS APIs like Gemini 2.5."""
        lines = []
        for line in self.dialogue:
            # Format: Speaker: text
            lines.append(f"{line.speaker}: {line.text}")
        return "\n\n".join(lines)

    def to_dia_format(self) -> str:
        """Convert to format suitable for Dia TTS model ([S1], [S2] tags)."""
        lines = []
        speaker_map = {}
        for line in self.dialogue:
            if line.speaker not in speaker_map:
                speaker_map[line.speaker] = f"S{len(speaker_map) + 1}"
            tag = f"[{speaker_map[line.speaker]}]"
            lines.append(f"{tag} {line.text}")
        return "\n".join(lines)


SCRIPT_PROMPT = """You are a world-class podcast producer creating an engaging two-host discussion show about what's trending on X (formerly Twitter).

SHOW DETAILS:
- Podcast: {podcast_name}
- Hosts: {host1} and {host2}
- Style: {style}
- Target length: {duration} minutes (approximately {word_count} words)

HOST PERSONALITIES:
- {host1}: The lead host who introduces topics, provides context, and drives the conversation. Energetic, witty, and well-informed. Uses phrases like "So get this..." or "Here's where it gets interesting..."
- {host2}: The co-host who reacts, asks great follow-up questions, and adds hot takes. Curious, sometimes skeptical, brings humor. Uses phrases like "Wait, seriously?" or "Okay but here's my take..."

TODAY'S TOPICS (from X/Twitter):
{topics_content}

SCRIPT REQUIREMENTS:
1. Create natural, lively dialogue - like two friends catching up on internet drama
2. Use short punchy sentences suitable for text-to-speech
3. Include natural speech patterns that make it feel REAL:
   - Reactions: "Oh wow", "No way", "That's insane", "I love that"
   - Thinking out loud: "I mean...", "Like...", "You know what I think?"
   - Agreement/disagreement: "Exactly!", "I don't know about that...", "Hard agree"
   - Laughter cues: "That's hilarious", "*laughs*", "I can't"
4. For each topic:
   - {host1} sets up the story with energy
   - {host2} reacts and asks what everyone's thinking
   - Both share opinions and hot takes
   - Keep it moving - don't overexplain
5. Transitions should feel natural: "Okay but speaking of drama...", "Alright, next up..."
6. Open with energy: "What's up everyone, welcome back to {podcast_name}!"
7. End with a fun sign-off, maybe tease what's coming

OUTPUT FORMAT (JSON):
{{
  "title": "Episode title - make it catchy!",
  "description": "Brief episode description",
  "topics_covered": ["topic1", "topic2"],
  "dialogue": [
    {{"speaker": "{host1}", "text": "dialogue text", "emotion": "excited"}},
    {{"speaker": "{host2}", "text": "dialogue text", "emotion": "curious"}}
  ]
}}

Emotions can be: neutral, excited, curious, surprised, thoughtful, amused, concerned, emphatic, sarcastic

Generate the complete podcast script:"""


class PodcastScriptGenerator:
    """Generates podcast scripts from analyzed tweets."""

    def __init__(self, config: ScriptConfig):
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
            # Default to OpenRouter
            self.client = AsyncOpenAI(
                api_key=api_key,
                base_url=config.base_url or OPENROUTER_BASE_URL,
            )

    async def generate_script(
        self,
        tweets: list[Tweet],
        analyses: dict[str, TweetAnalysis],
    ) -> PodcastScript:
        """
        Generate a podcast script from analyzed tweets.

        Args:
            tweets: List of tweets to include
            analyses: Analysis results for each tweet (keyed by tweet_id)
        """
        # Prepare content summary for each topic
        topics_content = self._prepare_topics_content(tweets, analyses)

        # Calculate target word count (~150 words per minute)
        target_words = self.config.target_duration_minutes * 150

        prompt = SCRIPT_PROMPT.format(
            podcast_name=self.config.podcast_name,
            host1=self.config.host1_name,
            host2=self.config.host2_name,
            style=self.config.style,
            duration=self.config.target_duration_minutes,
            word_count=target_words,
            topics_content=topics_content,
        )

        try:
            response = await self._call_llm(prompt)
            script = self._parse_script(response, tweets)
            return script

        except Exception as e:
            logger.error(f"Failed to generate script: {e}")
            raise

    def _prepare_topics_content(
        self,
        tweets: list[Tweet],
        analyses: dict[str, TweetAnalysis],
    ) -> str:
        """Format tweets and analyses into content for the prompt."""
        sections = []

        for tweet in tweets:
            analysis = analyses.get(tweet.tweet_id)
            if not analysis:
                continue

            section = f"""
TOPIC: {', '.join(analysis.topics)}
Interest Score: {analysis.interest_score}/10
Tweet from @{tweet.username}: "{tweet.text}"
Engagement: {tweet.likes:,} likes, {tweet.retweets:,} retweets

Why it's interesting: {analysis.reason}

Suggested talking points:
{chr(10).join(f'- {point}' for point in analysis.talking_points)}

Sentiment: {analysis.sentiment}
{"⚠️ Potentially controversial topic" if analysis.is_controversial else ""}
{"🚨 Breaking news!" if analysis.has_breaking_news else ""}
"""
            sections.append(section)

        return "\n---\n".join(sections)

    async def _call_llm(self, prompt: str) -> str:
        """Call LLM via OpenRouter or OpenAI-compatible API."""
        request_params = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a professional podcast script writer. "
                        "Create engaging, natural dialogue. Return valid JSON only."
                    )
                },
                {"role": "user", "content": prompt}
            ],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }

        # Try with JSON mode first, fallback without it
        try:
            response = await self.client.chat.completions.create(
                **request_params,
                response_format={"type": "json_object"}
            )
        except Exception:
            response = await self.client.chat.completions.create(**request_params)

        return response.choices[0].message.content

    def _parse_script(self, response: str, tweets: list[Tweet]) -> PodcastScript:
        """Parse LLM response into PodcastScript."""
        try:
            data = json.loads(response)

            dialogue = []
            for line in data.get("dialogue", []):
                dialogue.append(DialogueLine(
                    speaker=line.get("speaker", self.config.host1_name),
                    text=line.get("text", ""),
                    emotion=line.get("emotion"),
                ))

            return PodcastScript(
                title=data.get("title", f"{self.config.podcast_name} - {datetime.utcnow().strftime('%B %d')}"),
                description=data.get("description", ""),
                generated_at=datetime.utcnow(),
                target_duration_minutes=self.config.target_duration_minutes,
                dialogue=dialogue,
                source_tweet_ids=[t.tweet_id for t in tweets],
                topics_covered=data.get("topics_covered", []),
            )

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse script response: {e}")
            raise ValueError(f"Invalid script JSON: {e}")

    def estimate_duration(self, script: PodcastScript) -> float:
        """Estimate podcast duration in minutes based on word count."""
        total_words = sum(len(line.text.split()) for line in script.dialogue)
        # Average speaking rate: ~150 words per minute
        return total_words / 150


class QuickScriptGenerator:
    """
    Simplified script generator for quick podcast creation.
    Uses a single prompt for faster generation.
    """

    def __init__(self, config: ScriptConfig):
        self.config = config
        api_key = config.api_key or config.openai_api_key

        if config.provider == "openrouter":
            self.client = AsyncOpenAI(
                api_key=api_key,
                base_url=config.base_url or OPENROUTER_BASE_URL,
            )
        else:
            self.client = AsyncOpenAI(api_key=api_key)

    async def generate_from_text(self, content: str) -> str:
        """
        Generate a quick podcast script from raw text content.
        Returns script in Gemini TTS multi-speaker format.
        """
        prompt = f"""Create a short, engaging podcast dialogue between {self.config.host1_name} and {self.config.host2_name} discussing this content:

{content}

Requirements:
- Natural conversational style
- Short sentences (TTS-friendly)
- Include reactions and follow-up questions
- About {self.config.target_duration_minutes * 150} words total

Format each line as:
{self.config.host1_name}: [dialogue]
{self.config.host2_name}: [dialogue]

Generate the dialogue:"""

        response = await self.client.chat.completions.create(
            model=self.config.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=2048,
        )

        return response.choices[0].message.content
