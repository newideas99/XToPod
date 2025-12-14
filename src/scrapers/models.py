"""Data models for Twitter scraping."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field


class Tweet(BaseModel):
    """Represents a scraped tweet."""

    tweet_id: str = Field(..., description="Unique Twitter tweet ID")
    user_id: str = Field(..., description="User's Twitter ID")
    username: str = Field(..., description="User's handle (@username)")
    display_name: str = Field(..., description="User's display name")
    text: str = Field(..., description="Tweet text content")
    created_at: Optional[datetime] = Field(None, description="Tweet creation time")
    scraped_at: datetime = Field(default_factory=datetime.utcnow)

    # Engagement metrics
    likes: int = Field(default=0)
    retweets: int = Field(default=0)
    replies: int = Field(default=0)
    views: Optional[int] = Field(None)
    bookmarks: Optional[int] = Field(None)

    # Content metadata
    is_retweet: bool = Field(default=False)
    is_reply: bool = Field(default=False)
    is_quote: bool = Field(default=False)
    has_media: bool = Field(default=False)
    media_urls: list[str] = Field(default_factory=list)

    # URLs and references
    tweet_url: str = Field(default="")
    quoted_tweet_id: Optional[str] = Field(None)
    reply_to_tweet_id: Optional[str] = Field(None)

    # Feed source
    feed_type: str = Field(default="for_you", description="for_you, following, search, etc.")

    # Analysis fields (populated later by LLM)
    interest_score: Optional[float] = Field(None, ge=0, le=10)
    topics: list[str] = Field(default_factory=list)
    summary: Optional[str] = Field(None)


class ScrapingSession(BaseModel):
    """Metadata about a scraping session."""

    session_id: str
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: Optional[datetime] = None
    tweets_collected: int = Field(default=0)
    feed_type: str = Field(default="for_you")
    status: str = Field(default="running")  # running, completed, failed
    error_message: Optional[str] = None


class TweetThread(BaseModel):
    """Represents a Twitter thread (multiple connected tweets)."""

    thread_id: str  # Usually the ID of the first tweet
    tweets: list[Tweet] = Field(default_factory=list)
    author_username: str
    total_engagement: int = Field(default=0)

    def calculate_engagement(self) -> int:
        """Sum up all engagement across thread tweets."""
        total = sum(
            t.likes + t.retweets + t.replies
            for t in self.tweets
        )
        self.total_engagement = total
        return total
