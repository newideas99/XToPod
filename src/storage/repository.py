"""
Repository pattern for tweet storage operations.
"""

import json
from datetime import datetime, timedelta
from typing import Optional
import structlog

from .database import TweetDatabase
from ..scrapers.models import Tweet, ScrapingSession

logger = structlog.get_logger()


class TweetRepository:
    """Repository for tweet CRUD operations."""

    def __init__(self, db: TweetDatabase):
        self.db = db

    async def save_tweet(self, tweet: Tweet) -> bool:
        """
        Save or update a tweet in the database.
        Returns True if inserted, False if already exists.
        """
        sql = """
        INSERT INTO tweets (
            tweet_id, user_id, username, display_name, text, created_at, scraped_at,
            likes, retweets, replies, views, bookmarks,
            is_retweet, is_reply, is_quote, has_media, media_urls,
            tweet_url, quoted_tweet_id, reply_to_tweet_id, feed_type
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(tweet_id) DO UPDATE SET
            likes = excluded.likes,
            retweets = excluded.retweets,
            replies = excluded.replies,
            views = excluded.views,
            scraped_at = excluded.scraped_at
        """
        try:
            await self.db.connection.execute(sql, (
                tweet.tweet_id,
                tweet.user_id,
                tweet.username,
                tweet.display_name,
                tweet.text,
                tweet.created_at.isoformat() if tweet.created_at else None,
                tweet.scraped_at.isoformat(),
                tweet.likes,
                tweet.retweets,
                tweet.replies,
                tweet.views,
                tweet.bookmarks,
                tweet.is_retweet,
                tweet.is_reply,
                tweet.is_quote,
                tweet.has_media,
                json.dumps(tweet.media_urls),
                tweet.tweet_url,
                tweet.quoted_tweet_id,
                tweet.reply_to_tweet_id,
                tweet.feed_type,
            ))
            await self.db.connection.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to save tweet {tweet.tweet_id}: {e}")
            return False

    async def save_tweets_batch(self, tweets: list[Tweet]) -> int:
        """Save multiple tweets efficiently. Returns count of saved tweets."""
        saved = 0
        for tweet in tweets:
            if await self.save_tweet(tweet):
                saved += 1
        return saved

    async def get_tweet(self, tweet_id: str) -> Optional[Tweet]:
        """Get a single tweet by ID."""
        sql = "SELECT * FROM tweets WHERE tweet_id = ?"
        async with self.db.connection.execute(sql, (tweet_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_tweet(dict(row))
        return None

    async def get_recent_tweets(
        self,
        hours: int = 24,
        limit: int = 1000,
        min_interest_score: Optional[float] = None,
    ) -> list[Tweet]:
        """Get tweets from the last N hours."""
        cutoff = datetime.utcnow() - timedelta(hours=hours)

        sql = """
        SELECT * FROM tweets
        WHERE scraped_at >= ?
        """
        params = [cutoff.isoformat()]

        if min_interest_score is not None:
            sql += " AND interest_score >= ?"
            params.append(min_interest_score)

        sql += " ORDER BY scraped_at DESC LIMIT ?"
        params.append(limit)

        tweets = []
        async with self.db.connection.execute(sql, params) as cursor:
            async for row in cursor:
                tweets.append(self._row_to_tweet(dict(row)))
        return tweets

    async def get_unanalyzed_tweets(self, limit: int = 100) -> list[Tweet]:
        """Get tweets that haven't been analyzed by LLM yet."""
        sql = """
        SELECT * FROM tweets
        WHERE analyzed_at IS NULL
        ORDER BY scraped_at DESC
        LIMIT ?
        """
        tweets = []
        async with self.db.connection.execute(sql, (limit,)) as cursor:
            async for row in cursor:
                tweets.append(self._row_to_tweet(dict(row)))
        return tweets

    async def get_top_tweets(
        self,
        hours: int = 24,
        limit: int = 20,
        min_interest_score: float = 6.0,
    ) -> list[Tweet]:
        """Get the most interesting tweets for podcast generation."""
        cutoff = datetime.utcnow() - timedelta(hours=hours)

        # First try to get recent tweets
        sql = """
        SELECT * FROM tweets
        WHERE scraped_at >= ?
          AND interest_score >= ?
          AND included_in_episode IS NULL
        ORDER BY interest_score DESC, (likes + retweets * 2) DESC
        LIMIT ?
        """
        tweets = []
        async with self.db.connection.execute(sql, (
            cutoff.isoformat(), min_interest_score, limit
        )) as cursor:
            async for row in cursor:
                tweets.append(self._row_to_tweet(dict(row)))

        # If no recent tweets, get the best available (fallback for testing)
        if not tweets:
            logger.info("No recent tweets found, falling back to all available tweets")
            sql = """
            SELECT * FROM tweets
            WHERE interest_score >= ?
              AND included_in_episode IS NULL
            ORDER BY interest_score DESC, (likes + retweets * 2) DESC
            LIMIT ?
            """
            async with self.db.connection.execute(sql, (min_interest_score, limit)) as cursor:
                async for row in cursor:
                    tweets.append(self._row_to_tweet(dict(row)))

        return tweets

    async def update_analysis(
        self,
        tweet_id: str,
        interest_score: float,
        topics: list[str],
        summary: Optional[str] = None,
    ) -> None:
        """Update tweet with LLM analysis results."""
        sql = """
        UPDATE tweets
        SET interest_score = ?,
            topics = ?,
            summary = ?,
            analyzed_at = ?
        WHERE tweet_id = ?
        """
        await self.db.connection.execute(sql, (
            interest_score,
            json.dumps(topics),
            summary,
            datetime.utcnow().isoformat(),
            tweet_id,
        ))
        await self.db.connection.commit()

    async def mark_included_in_episode(
        self,
        tweet_ids: list[str],
        episode_id: str,
    ) -> None:
        """Mark tweets as included in a podcast episode."""
        sql = "UPDATE tweets SET included_in_episode = ? WHERE tweet_id = ?"
        for tweet_id in tweet_ids:
            await self.db.connection.execute(sql, (episode_id, tweet_id))
        await self.db.connection.commit()

    async def search_tweets(self, query: str, limit: int = 50) -> list[Tweet]:
        """Full-text search across tweets."""
        sql = """
        SELECT tweets.* FROM tweets
        JOIN tweets_fts ON tweets.id = tweets_fts.rowid
        WHERE tweets_fts MATCH ?
        ORDER BY rank
        LIMIT ?
        """
        tweets = []
        async with self.db.connection.execute(sql, (query, limit)) as cursor:
            async for row in cursor:
                tweets.append(self._row_to_tweet(dict(row)))
        return tweets

    async def get_stats(self) -> dict:
        """Get database statistics."""
        stats = {}

        # Total tweets
        async with self.db.connection.execute("SELECT COUNT(*) FROM tweets") as cursor:
            stats["total_tweets"] = (await cursor.fetchone())[0]

        # Tweets today
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        async with self.db.connection.execute(
            "SELECT COUNT(*) FROM tweets WHERE scraped_at >= ?",
            (today.isoformat(),)
        ) as cursor:
            stats["tweets_today"] = (await cursor.fetchone())[0]

        # Analyzed tweets
        async with self.db.connection.execute(
            "SELECT COUNT(*) FROM tweets WHERE analyzed_at IS NOT NULL"
        ) as cursor:
            stats["analyzed_tweets"] = (await cursor.fetchone())[0]

        # Average interest score
        async with self.db.connection.execute(
            "SELECT AVG(interest_score) FROM tweets WHERE interest_score IS NOT NULL"
        ) as cursor:
            avg = (await cursor.fetchone())[0]
            stats["avg_interest_score"] = round(avg, 2) if avg else 0

        return stats

    async def cleanup_old_tweets(self, days: int = 30) -> int:
        """Delete tweets older than N days. Returns count deleted."""
        cutoff = datetime.utcnow() - timedelta(days=days)
        sql = "DELETE FROM tweets WHERE scraped_at < ? AND included_in_episode IS NULL"
        cursor = await self.db.connection.execute(sql, (cutoff.isoformat(),))
        await self.db.connection.commit()
        return cursor.rowcount

    def _row_to_tweet(self, row: dict) -> Tweet:
        """Convert database row to Tweet model."""
        # Parse JSON fields
        media_urls = json.loads(row.get("media_urls") or "[]")
        topics = json.loads(row.get("topics") or "[]")

        # Parse datetime fields
        created_at = None
        if row.get("created_at"):
            try:
                created_at = datetime.fromisoformat(row["created_at"])
            except ValueError:
                pass

        scraped_at = datetime.utcnow()
        if row.get("scraped_at"):
            try:
                scraped_at = datetime.fromisoformat(row["scraped_at"])
            except ValueError:
                pass

        return Tweet(
            tweet_id=row["tweet_id"],
            user_id=row["user_id"],
            username=row["username"],
            display_name=row["display_name"],
            text=row["text"],
            created_at=created_at,
            scraped_at=scraped_at,
            likes=row.get("likes", 0),
            retweets=row.get("retweets", 0),
            replies=row.get("replies", 0),
            views=row.get("views"),
            bookmarks=row.get("bookmarks"),
            is_retweet=bool(row.get("is_retweet")),
            is_reply=bool(row.get("is_reply")),
            is_quote=bool(row.get("is_quote")),
            has_media=bool(row.get("has_media")),
            media_urls=media_urls,
            tweet_url=row.get("tweet_url", ""),
            quoted_tweet_id=row.get("quoted_tweet_id"),
            reply_to_tweet_id=row.get("reply_to_tweet_id"),
            feed_type=row.get("feed_type", "for_you"),
            interest_score=row.get("interest_score"),
            topics=topics,
            summary=row.get("summary"),
        )


class SessionRepository:
    """Repository for scraping session tracking."""

    def __init__(self, db: TweetDatabase):
        self.db = db

    async def save_session(self, session: ScrapingSession) -> None:
        """Save or update a scraping session."""
        sql = """
        INSERT INTO scraping_sessions (
            session_id, started_at, ended_at, tweets_collected, feed_type, status, error_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            ended_at = excluded.ended_at,
            tweets_collected = excluded.tweets_collected,
            status = excluded.status,
            error_message = excluded.error_message
        """
        await self.db.connection.execute(sql, (
            session.session_id,
            session.started_at.isoformat(),
            session.ended_at.isoformat() if session.ended_at else None,
            session.tweets_collected,
            session.feed_type,
            session.status,
            session.error_message,
        ))
        await self.db.connection.commit()

    async def get_recent_sessions(self, limit: int = 10) -> list[dict]:
        """Get recent scraping sessions."""
        sql = """
        SELECT * FROM scraping_sessions
        ORDER BY started_at DESC
        LIMIT ?
        """
        sessions = []
        async with self.db.connection.execute(sql, (limit,)) as cursor:
            async for row in cursor:
                sessions.append(dict(row))
        return sessions
