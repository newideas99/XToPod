"""
Xtopod - Automated Twitter/X to Podcast Pipeline

This package provides tools to:
1. Scrape tweets from Twitter/X's "For You" algorithmic feed
2. Store and organize tweets in SQLite
3. Use LLMs to analyze and summarize interesting content
4. Generate multi-speaker podcast episodes using open-notebook/podcastfy

Built for the 2025 landscape where:
- X API doesn't expose the algorithmic "For You" feed
- Browser automation with Playwright is required for scraping
- Gemini 2.5 TTS and open-source Dia provide NotebookLM-quality audio
"""

__version__ = "0.1.0"
__author__ = "Xtopod Team"
