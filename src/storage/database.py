"""
SQLite database for storing scraped tweets and podcast metadata.

SQLite handles 6.5+ million records efficiently and a single file simplifies backups.
"""

import aiosqlite
from pathlib import Path
from datetime import datetime
from typing import Optional
import structlog

logger = structlog.get_logger()

# SQL Schema
SCHEMA = """
-- Tweets table: stores all scraped tweets
CREATE TABLE IF NOT EXISTS tweets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tweet_id TEXT UNIQUE NOT NULL,
    user_id TEXT NOT NULL,
    username TEXT NOT NULL,
    display_name TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TIMESTAMP,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Engagement metrics
    likes INTEGER DEFAULT 0,
    retweets INTEGER DEFAULT 0,
    replies INTEGER DEFAULT 0,
    views INTEGER,
    bookmarks INTEGER,

    -- Content metadata
    is_retweet BOOLEAN DEFAULT FALSE,
    is_reply BOOLEAN DEFAULT FALSE,
    is_quote BOOLEAN DEFAULT FALSE,
    has_media BOOLEAN DEFAULT FALSE,
    media_urls TEXT,  -- JSON array

    -- URLs and references
    tweet_url TEXT,
    quoted_tweet_id TEXT,
    reply_to_tweet_id TEXT,

    -- Feed source
    feed_type TEXT DEFAULT 'for_you',

    -- Analysis fields (populated by LLM)
    interest_score REAL,
    topics TEXT,  -- JSON array
    summary TEXT,
    analyzed_at TIMESTAMP,

    -- Podcast inclusion
    included_in_episode TEXT,  -- Episode ID if included

    -- Indexes for common queries
    CONSTRAINT valid_interest CHECK (interest_score IS NULL OR (interest_score >= 0 AND interest_score <= 10))
);

-- Scraping sessions table
CREATE TABLE IF NOT EXISTS scraping_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT UNIQUE NOT NULL,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    tweets_collected INTEGER DEFAULT 0,
    feed_type TEXT DEFAULT 'for_you',
    status TEXT DEFAULT 'running',  -- running, completed, failed
    error_message TEXT
);

-- Podcast episodes table
CREATE TABLE IF NOT EXISTS podcast_episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    published_at TIMESTAMP,

    -- Content
    source_tweets TEXT,  -- JSON array of tweet IDs
    script TEXT,
    transcript TEXT,

    -- Audio
    audio_file TEXT,
    duration_seconds INTEGER,

    -- Generation metadata
    llm_model TEXT,
    tts_provider TEXT,
    generation_cost REAL,
    status TEXT DEFAULT 'pending'  -- pending, generating, completed, failed
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_tweets_scraped_at ON tweets(scraped_at);
CREATE INDEX IF NOT EXISTS idx_tweets_interest ON tweets(interest_score DESC) WHERE interest_score IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tweets_username ON tweets(username);
CREATE INDEX IF NOT EXISTS idx_tweets_feed_type ON tweets(feed_type);
CREATE INDEX IF NOT EXISTS idx_tweets_not_analyzed ON tweets(analyzed_at) WHERE analyzed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_episodes_status ON podcast_episodes(status);

-- Full-text search for tweets
CREATE VIRTUAL TABLE IF NOT EXISTS tweets_fts USING fts5(
    text,
    username,
    display_name,
    content='tweets',
    content_rowid='id'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS tweets_ai AFTER INSERT ON tweets BEGIN
    INSERT INTO tweets_fts(rowid, text, username, display_name)
    VALUES (new.id, new.text, new.username, new.display_name);
END;

CREATE TRIGGER IF NOT EXISTS tweets_ad AFTER DELETE ON tweets BEGIN
    INSERT INTO tweets_fts(tweets_fts, rowid, text, username, display_name)
    VALUES ('delete', old.id, old.text, old.username, old.display_name);
END;

CREATE TRIGGER IF NOT EXISTS tweets_au AFTER UPDATE ON tweets BEGIN
    INSERT INTO tweets_fts(tweets_fts, rowid, text, username, display_name)
    VALUES ('delete', old.id, old.text, old.username, old.display_name);
    INSERT INTO tweets_fts(rowid, text, username, display_name)
    VALUES (new.id, new.text, new.username, new.display_name);
END;
"""


class TweetDatabase:
    """Async SQLite database wrapper for tweet storage."""

    def __init__(self, db_path: Path | str = "data/xtopod.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection: Optional[aiosqlite.Connection] = None

    async def connect(self) -> None:
        """Open database connection."""
        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row
        # Enable foreign keys and WAL mode for better performance
        await self._connection.execute("PRAGMA foreign_keys = ON")
        await self._connection.execute("PRAGMA journal_mode = WAL")
        logger.info(f"Connected to database: {self.db_path}")

    async def close(self) -> None:
        """Close database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None

    async def initialize(self) -> None:
        """Create tables and indexes."""
        if not self._connection:
            await self.connect()
        await self._connection.executescript(SCHEMA)
        await self._connection.commit()
        logger.info("Database schema initialized")

    @property
    def connection(self) -> aiosqlite.Connection:
        if not self._connection:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._connection

    async def __aenter__(self) -> "TweetDatabase":
        await self.connect()
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()


async def init_database(db_path: Path | str = "data/xtopod.db") -> TweetDatabase:
    """Initialize and return a database instance."""
    db = TweetDatabase(db_path)
    await db.connect()
    await db.initialize()
    return db
