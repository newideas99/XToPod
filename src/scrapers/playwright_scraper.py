"""
Playwright-based Twitter/X scraper for the algorithmic "For You" feed.

The "For You" feed is NOT available via X's official API - only browser automation
can access it. This scraper:
1. Uses your authenticated session (via cookies)
2. Intercepts GraphQL responses to extract tweet data
3. Handles X's anti-bot detection with careful timing

Legal note: The May 2024 X Corp. v. Bright Data ruling established that scraping
publicly accessible data is legally defensible, though it violates X's ToS.
Use responsibly with your own authenticated account.
"""

import asyncio
import json
import random
import re
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Optional

from playwright.async_api import async_playwright, Page, BrowserContext, Response
from pydantic import BaseModel
import structlog

from .models import Tweet, ScrapingSession

logger = structlog.get_logger()


class ScraperConfig(BaseModel):
    """Configuration for the Playwright scraper."""

    cookies_file: Optional[Path] = None
    auth_token: Optional[str] = None
    ct0_token: Optional[str] = None

    headless: bool = False  # Headless mode triggers more bot detection
    slow_mo: int = 50  # Milliseconds to slow down actions

    scroll_delay_min: float = 1.5
    scroll_delay_max: float = 4.0
    max_scrolls: int = 50
    tweets_per_session: int = 100

    proxy: Optional[str] = None
    user_agent: Optional[str] = None

    # Data directory for storing session state
    data_dir: Path = Path("data/browser")


class PlaywrightScraper:
    """
    Scrapes Twitter/X's "For You" feed using Playwright browser automation.

    Usage:
        scraper = PlaywrightScraper(config)
        async for tweet in scraper.scrape_for_you_feed():
            print(tweet.text)
    """

    def __init__(self, config: ScraperConfig):
        self.config = config
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        self._collected_tweets: dict[str, Tweet] = {}
        self._session: Optional[ScrapingSession] = None

    async def _setup_browser(self) -> tuple[BrowserContext, Page]:
        """Initialize browser with authentication."""
        playwright = await async_playwright().start()

        # Browser launch options
        launch_options = {
            "headless": self.config.headless,
            "slow_mo": self.config.slow_mo,
        }

        if self.config.proxy:
            launch_options["proxy"] = {"server": self.config.proxy}

        browser = await playwright.chromium.launch(**launch_options)

        # Context options for anti-detection
        context_options = {
            "viewport": {"width": 1920, "height": 1080},
            "user_agent": self.config.user_agent or (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "locale": "en-US",
            "timezone_id": "America/New_York",
        }

        # Load existing session state if available
        state_file = self.config.data_dir / "session_state.json"
        if state_file.exists():
            context_options["storage_state"] = str(state_file)
            logger.info("Loaded existing browser session state")

        context = await browser.new_context(**context_options)

        # Add cookies if provided
        await self._add_authentication(context)

        page = await context.new_page()

        # Set up response interception for GraphQL data
        page.on("response", self._handle_response)

        return context, page

    async def _add_authentication(self, context: BrowserContext) -> None:
        """Add authentication cookies to the browser context."""
        cookies = []

        # Method 1: Load from cookies file
        if self.config.cookies_file and self.config.cookies_file.exists():
            with open(self.config.cookies_file) as f:
                cookies_data = json.load(f)
                if isinstance(cookies_data, list):
                    cookies = cookies_data
                elif isinstance(cookies_data, dict):
                    # Convert dict format to list format
                    for name, value in cookies_data.items():
                        cookies.append({
                            "name": name,
                            "value": value,
                            "domain": ".x.com",
                            "path": "/",
                        })

        # Method 2: Use provided tokens directly
        if self.config.auth_token:
            cookies.append({
                "name": "auth_token",
                "value": self.config.auth_token,
                "domain": ".x.com",
                "path": "/",
                "httpOnly": True,
                "secure": True,
            })

        if self.config.ct0_token:
            cookies.append({
                "name": "ct0",
                "value": self.config.ct0_token,
                "domain": ".x.com",
                "path": "/",
            })

        if cookies:
            await context.add_cookies(cookies)
            logger.info(f"Added {len(cookies)} authentication cookies")

    async def _handle_response(self, response: Response) -> None:
        """Intercept and parse GraphQL responses containing tweet data."""
        url = response.url

        # Look for HomeTimeline and ForYou GraphQL endpoints
        if "graphql" in url and any(endpoint in url for endpoint in [
            "HomeTimeline",
            "HomeLatestTimeline",
            "ForYou",
            "TweetDetail",
        ]):
            try:
                data = await response.json()
                tweets = self._extract_tweets_from_response(data)
                for tweet in tweets:
                    if tweet.tweet_id not in self._collected_tweets:
                        self._collected_tweets[tweet.tweet_id] = tweet
                        logger.debug(f"Collected tweet {tweet.tweet_id} from @{tweet.username}")
            except Exception as e:
                logger.warning(f"Failed to parse response from {url}: {e}")

    def _extract_tweets_from_response(self, data: dict) -> list[Tweet]:
        """
        Extract tweet data from Twitter's GraphQL response structure.

        Twitter's response format is deeply nested. Key paths:
        - data.home.home_timeline_urt.instructions[].entries[].content.itemContent.tweet_results.result
        """
        tweets = []

        def find_tweet_results(obj: any, path: str = "") -> list[dict]:
            """Recursively find all tweet_results objects."""
            results = []
            if isinstance(obj, dict):
                if "tweet_results" in obj:
                    result = obj["tweet_results"].get("result", {})
                    if result:
                        results.append(result)
                # Also check for legacy tweet format
                if "legacy" in obj and "full_text" in obj.get("legacy", {}):
                    results.append(obj)
                # Recurse into dict values
                for key, value in obj.items():
                    results.extend(find_tweet_results(value, f"{path}.{key}"))
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    results.extend(find_tweet_results(item, f"{path}[{i}]"))
            return results

        tweet_objects = find_tweet_results(data)

        for tweet_obj in tweet_objects:
            try:
                tweet = self._parse_tweet_object(tweet_obj)
                if tweet:
                    tweets.append(tweet)
            except Exception as e:
                logger.debug(f"Failed to parse tweet object: {e}")

        return tweets

    def _parse_tweet_object(self, obj: dict) -> Optional[Tweet]:
        """Parse a single tweet object from GraphQL response."""
        # Handle different tweet object structures
        legacy = obj.get("legacy", obj)
        core = obj.get("core", {})
        user_results = core.get("user_results", {}).get("result", {})
        user_legacy = user_results.get("legacy", {})

        # Extract required fields
        tweet_id = obj.get("rest_id") or legacy.get("id_str")
        if not tweet_id:
            return None

        text = legacy.get("full_text", "")
        if not text:
            return None

        # Parse user info
        user_id = user_results.get("rest_id", "")
        username = user_legacy.get("screen_name", "")
        display_name = user_legacy.get("name", username)

        # Parse engagement metrics
        likes = legacy.get("favorite_count", 0)
        retweets = legacy.get("retweet_count", 0)
        replies = legacy.get("reply_count", 0)
        views = None
        if "views" in obj:
            views = int(obj["views"].get("count", 0))

        # Parse timestamps
        created_at = None
        if "created_at" in legacy:
            try:
                created_at = datetime.strptime(
                    legacy["created_at"],
                    "%a %b %d %H:%M:%S %z %Y"
                )
            except ValueError:
                pass

        # Parse media
        media_urls = []
        has_media = False
        extended_entities = legacy.get("extended_entities", {})
        if "media" in extended_entities:
            has_media = True
            for media in extended_entities["media"]:
                media_urls.append(media.get("media_url_https", ""))

        # Parse tweet type
        is_retweet = "retweeted_status_result" in obj or legacy.get("retweeted", False)
        is_reply = bool(legacy.get("in_reply_to_status_id_str"))
        is_quote = "quoted_status_result" in obj

        return Tweet(
            tweet_id=tweet_id,
            user_id=user_id,
            username=username,
            display_name=display_name,
            text=text,
            created_at=created_at,
            likes=likes,
            retweets=retweets,
            replies=replies,
            views=views,
            is_retweet=is_retweet,
            is_reply=is_reply,
            is_quote=is_quote,
            has_media=has_media,
            media_urls=media_urls,
            tweet_url=f"https://x.com/{username}/status/{tweet_id}",
            reply_to_tweet_id=legacy.get("in_reply_to_status_id_str"),
            feed_type="for_you",
        )

    async def _random_delay(self) -> None:
        """Add a random human-like delay."""
        delay = random.uniform(
            self.config.scroll_delay_min,
            self.config.scroll_delay_max
        )
        await asyncio.sleep(delay)

    async def _scroll_page(self, page: Page) -> None:
        """Scroll the page to load more tweets."""
        # Scroll to absolute bottom each time - way faster than incremental scrolling
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        # Wait for new content to load
        await asyncio.sleep(random.uniform(1.5, 2.0))

    async def scrape_for_you_feed(
        self,
        max_tweets: Optional[int] = None
    ) -> AsyncGenerator[Tweet, None]:
        """
        Scrape tweets from the "For You" algorithmic feed.

        Yields tweets as they are collected. Handles pagination by scrolling.
        """
        max_tweets = max_tweets or self.config.tweets_per_session

        self._session = ScrapingSession(
            session_id=datetime.utcnow().strftime("%Y%m%d_%H%M%S"),
            feed_type="for_you",
        )
        self._collected_tweets = {}

        context, page = await self._setup_browser()

        try:
            # Navigate to Twitter home (For You is the default tab)
            logger.info("Navigating to Twitter/X home feed...")
            # Use domcontentloaded instead of networkidle - Twitter never reaches idle state
            await page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=60000)
            await self._random_delay()

            # Wait for the feed to load (give Twitter time to hydrate after DOM loads)
            try:
                await page.wait_for_selector('[data-testid="tweet"]', timeout=30000)
                logger.info("Feed loaded successfully")
            except Exception:
                logger.error("Failed to load feed - check authentication")
                raise

            # Scroll and collect tweets
            scrolls = 0
            last_count = 0
            no_new_tweets_count = 0

            while len(self._collected_tweets) < max_tweets and scrolls < self.config.max_scrolls:
                await self._scroll_page(page)
                scrolls += 1

                # Yield any new tweets
                current_count = len(self._collected_tweets)
                if current_count > last_count:
                    new_tweets = list(self._collected_tweets.values())[last_count:current_count]
                    for tweet in new_tweets:
                        yield tweet
                        self._session.tweets_collected += 1
                    last_count = current_count
                    no_new_tweets_count = 0
                else:
                    no_new_tweets_count += 1
                    # Twitter can have gaps - scroll to absolute bottom to trigger loading
                    if no_new_tweets_count >= 2:
                        logger.debug("No new tweets, scrolling to bottom...")
                        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        await asyncio.sleep(2.0)
                    if no_new_tweets_count >= 8:
                        logger.info("No new tweets after 8 attempts, ending session")
                        break

                logger.info(
                    f"Scroll {scrolls}: collected {current_count}/{max_tweets} tweets"
                )

            self._session.status = "completed"
            self._session.ended_at = datetime.utcnow()

            # Save session state for future runs
            state_file = self.config.data_dir / "session_state.json"
            await context.storage_state(path=str(state_file))

        except Exception as e:
            self._session.status = "failed"
            self._session.error_message = str(e)
            logger.error(f"Scraping failed: {e}")
            raise

        finally:
            await context.close()

    async def scrape_user_timeline(
        self,
        username: str,
        max_tweets: int = 50
    ) -> AsyncGenerator[Tweet, None]:
        """Scrape tweets from a specific user's timeline."""
        self._collected_tweets = {}
        context, page = await self._setup_browser()

        try:
            url = f"https://x.com/{username}"
            logger.info(f"Navigating to @{username}'s profile...")
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await self._random_delay()

            await page.wait_for_selector('[data-testid="tweet"]', timeout=10000)

            scrolls = 0
            last_count = 0

            while len(self._collected_tweets) < max_tweets and scrolls < self.config.max_scrolls:
                await self._scroll_page(page)
                scrolls += 1

                current_count = len(self._collected_tweets)
                if current_count > last_count:
                    new_tweets = list(self._collected_tweets.values())[last_count:current_count]
                    for tweet in new_tweets:
                        tweet.feed_type = f"user_{username}"
                        yield tweet
                    last_count = current_count

        finally:
            await context.close()

    async def scrape_search(
        self,
        query: str,
        max_tweets: int = 50
    ) -> AsyncGenerator[Tweet, None]:
        """Scrape tweets from a search query."""
        self._collected_tweets = {}
        context, page = await self._setup_browser()

        try:
            # URL encode the query
            encoded_query = query.replace(" ", "%20")
            url = f"https://x.com/search?q={encoded_query}&src=typed_query&f=live"

            logger.info(f"Searching for: {query}")
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await self._random_delay()

            await page.wait_for_selector('[data-testid="tweet"]', timeout=10000)

            scrolls = 0
            last_count = 0

            while len(self._collected_tweets) < max_tweets and scrolls < self.config.max_scrolls:
                await self._scroll_page(page)
                scrolls += 1

                current_count = len(self._collected_tweets)
                if current_count > last_count:
                    new_tweets = list(self._collected_tweets.values())[last_count:current_count]
                    for tweet in new_tweets:
                        tweet.feed_type = f"search_{query}"
                        yield tweet
                    last_count = current_count

        finally:
            await context.close()


# Convenience function for quick scraping
async def scrape_for_you(
    auth_token: str,
    ct0_token: str,
    max_tweets: int = 100,
) -> list[Tweet]:
    """
    Convenience function to quickly scrape the For You feed.

    Example:
        tweets = await scrape_for_you(
            auth_token="your_auth_token",
            ct0_token="your_ct0_token",
            max_tweets=50
        )
    """
    config = ScraperConfig(
        auth_token=auth_token,
        ct0_token=ct0_token,
        tweets_per_session=max_tweets,
    )
    scraper = PlaywrightScraper(config)
    tweets = []
    async for tweet in scraper.scrape_for_you_feed(max_tweets):
        tweets.append(tweet)
    return tweets
