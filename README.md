# Xtopod - X to Podcast Pipeline

Automatically transform your X "For You" feed into **X Digest** - a daily AI-generated podcast with NotebookLM-quality multi-speaker dialogue.

## Features

- **Scrape X's Algorithmic Feed**: Uses Playwright browser automation to access the "For You" feed (not available via API)
- **AI-Powered Curation**: Gemini 2.5 Flash analyzes posts to find the most interesting content
- **Natural Podcast Scripts**: AI generates engaging two-host dialogue with hot takes and banter
- **NotebookLM-Quality Audio**: Gemini 2.5 TTS creates natural multi-speaker podcasts
- **Fully Automated**: Hourly collection + daily podcast generation

## One-Click Launch

### macOS
Double-click `launch.command` to start the full pipeline.

### Windows
Double-click `launch.bat` to start the full pipeline.

**First-time setup is fully interactive!** The scripts will:
1. Open your browser to get API keys (OpenRouter + Google)
2. Guide you through extracting X cookies
3. Auto-generate your `.env` and `cookies.json` files
4. Set up Python virtual environment
5. Install all dependencies (including bundled ffmpeg)
6. Install browser for scraping
7. Run the full pipeline and output an MP3 podcast

## Cost Breakdown

| Component | Budget Option | Premium Option |
|-----------|---------------|----------------|
| Hosting | Your computer ($0) | DigitalOcean $4-7/mo |
| LLM APIs | Gemini via OpenRouter (~$2-5/mo) | Claude Sonnet ($10-15/mo) |
| TTS | Gemini 2.5 (~$6-12/mo) | ElevenLabs ($22-99/mo) |
| **Total** | **~$8-15/month** | **$35-120/month** |

## Quick Start (Manual)

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/xtopod.git
cd xtopod

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows

# Install dependencies
pip install -e .

# Install Playwright browsers
playwright install chromium
```

### 2. Configuration

```bash
# Initialize project structure
xtopod init

# Copy and edit configuration
cp .env.example .env
```

Edit `.env` with your credentials:

```env
# LLM Provider - uses OpenRouter for Gemini access
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-v1-your-key-here

# Model settings (Gemini 2.5 Flash via OpenRouter)
GEMINI_MODEL=google/gemini-2.5-flash-preview-09-2025
ANALYSIS_MODEL=google/gemini-2.5-flash-preview-09-2025
SCRIPT_MODEL=google/gemini-2.5-flash-preview-09-2025

# TTS Provider - Gemini for multi-speaker podcasts
TTS_PROVIDER=gemini
GOOGLE_API_KEY=your_google_api_key_here

# Optional: Anthropic Claude (alternative to Gemini)
# ANTHROPIC_API_KEY=sk-ant-...
```

**Getting API Keys:**
- **OpenRouter**: Sign up at [openrouter.ai](https://openrouter.ai) → Dashboard → API Keys
- **Google API Key**: Go to [Google AI Studio](https://aistudio.google.com/app/apikey) → Create API Key

### 3. Getting Twitter Cookies

Xtopod uses your browser cookies to access Twitter's "For You" feed. Here's how to get them:

#### Option A: Export Full Cookie File (Recommended)

1. Install the [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc) Chrome extension (or equivalent for your browser)
2. Go to [x.com](https://x.com) and make sure you're logged in
3. Click the extension icon and select "Export" or "Download cookies.txt"
4. Save the file as `cookies.txt` in the Xtopod folder
5. Run the cookie converter:
   ```bash
   python3 scripts/convert_cookies.py
   ```

#### Option B: Manual Cookie Extraction

1. Go to [x.com](https://x.com) and log in
2. Open Developer Tools:
   - **Chrome/Edge**: Press `F12` or `Ctrl+Shift+I` (Windows) / `Cmd+Option+I` (Mac)
   - **Firefox**: Press `F12` or `Ctrl+Shift+I`
   - **Safari**: Enable Developer menu in Preferences → Advanced, then `Cmd+Option+I`
3. Go to the **Application** tab (Chrome/Edge) or **Storage** tab (Firefox)
4. In the left sidebar, expand **Cookies** → click `https://x.com`
5. Find and copy these cookie values:

| Cookie Name | What to Copy |
|-------------|--------------|
| `auth_token` | The long string value (e.g., `abc123def456...`) |
| `ct0` | The long string value |

6. Create a `cookies.json` file in the Xtopod folder:
```json
[
  {
    "name": "auth_token",
    "value": "YOUR_AUTH_TOKEN_HERE",
    "domain": ".x.com",
    "path": "/"
  },
  {
    "name": "ct0",
    "value": "YOUR_CT0_TOKEN_HERE",
    "domain": ".x.com",
    "path": "/"
  }
]
```

#### Cookie Troubleshooting

- **Cookies expire** after ~30 days or when you log out. Re-export if you get auth errors.
- **Use your main browser** where you're logged into Twitter, not an incognito window.
- **Don't share cookies** - they provide full access to your Twitter account!

### 4. Run the Pipeline

```bash
# Collect tweets from your For You feed
xtopod collect

# Analyze tweets with AI
xtopod analyze

# Generate podcast
xtopod generate

# Or run everything at once
xtopod run
```

### 5. Automated Scheduling

```bash
# Start automated scheduler
# - Collects tweets every hour
# - Generates podcast daily at 6 AM UTC
xtopod serve

# Custom schedule
xtopod serve --interval 30 --hour 8
```

## Architecture

```
HOURLY: Twitter/X (Playwright) → Collection Script → SQLite Database
                                                          │
DAILY:  Query 24h Data → LLM Summarization → Script Generation → TTS → MP3 Podcast
```

### Components

1. **Scraper** (`src/scrapers/`): Playwright-based browser automation for Twitter/X
2. **Storage** (`src/storage/`): SQLite database with FTS5 for tweet storage
3. **Processors** (`src/processors/`): LLM-based analysis and script generation
4. **TTS** (`src/tts/`): Multiple TTS providers (Gemini, ElevenLabs, OpenAI)
5. **Pipeline** (`src/pipeline/`): Orchestration and scheduling

## CLI Commands

```bash
python -m src.cli quick     # One-shot: collect → analyze → generate MP3 (recommended)
python -m src.cli collect   # Collect tweets from For You feed
python -m src.cli analyze   # Analyze tweets with LLM
python -m src.cli generate  # Generate podcast episode
python -m src.cli stats     # Show statistics
```

## TTS Provider Comparison

| Provider | Quality | Multi-Speaker | Monthly Cost |
|----------|---------|---------------|--------------|
| **Gemini 2.5** | ⭐⭐⭐⭐ | Native 2-speaker | $6-12 |
| **ElevenLabs** | ⭐⭐⭐⭐⭐ | Manual switching | $99-330 |
| **OpenAI** | ⭐⭐⭐⭐ | Manual switching | $7-15 |

**Recommendation**: Use Gemini 2.5 for the best balance of quality and cost. It's the only provider with native multi-speaker support, creating truly natural podcast-style dialogue.

## Using with Open-Notebook

This project can integrate with [Open-Notebook](https://github.com/lfnovo/open-notebook) for a complete NotebookLM alternative:

```bash
# Clone open-notebook for additional features
git clone https://github.com/lfnovo/open-notebook.git

# Use open-notebook's podcast generation with our tweet content
```

## Project Structure

```
xtopod/
├── launch.command         # One-click launcher (macOS)
├── launch.bat             # One-click launcher (Windows)
├── src/
│   ├── scrapers/          # Twitter scraping with Playwright
│   ├── storage/           # SQLite database layer
│   ├── processors/        # LLM analysis and script generation
│   ├── tts/               # Text-to-speech providers (Gemini, ElevenLabs, OpenAI)
│   ├── pipeline/          # Orchestration and scheduling
│   └── cli.py             # Command-line interface
├── data/                  # SQLite database
├── output/                # Generated MP3 podcasts
├── pyproject.toml
├── .env.example
└── README.md
```

## Legal Considerations

- **Scraping**: The May 2024 X Corp. v. Bright Data ruling established that scraping publicly accessible data is legally defensible
- **Terms of Service**: Scraping may violate X's ToS, which could result in account suspension
- **Recommendation**: Use for personal use with your own authenticated account

## Troubleshooting

### "Failed to load feed - check authentication"

Your cookies may have expired. Get fresh `auth_token` and `ct0` values from your browser.

### "No interesting tweets found"

- Lower the `MIN_INTEREST_SCORE` in your `.env`
- Make sure you've run `xtopod analyze` before `xtopod generate`
- Check that tweets were collected: `xtopod stats`

### Rate limiting / Account issues

- Don't run in headless mode (more likely to trigger bot detection)
- Add longer delays between scraping sessions
- Consider using a residential proxy

## Contributing

Contributions welcome! Areas of interest:

- Additional TTS providers (Dia model, Coqui XTTS)
- Better anti-detection for scraping
- Web UI for configuration
- RSS feed output

## License

MIT License - see LICENSE file.

## Acknowledgments

- [Open-Notebook](https://github.com/lfnovo/open-notebook) - Inspiration and podcast generation patterns
- [Podcastfy](https://github.com/souzatharsis/podcastfy) - Multi-modal podcast generation
- [twscrape](https://github.com/vladkens/twscrape) - Twitter API patterns
- [Nari Labs Dia](https://github.com/nari-labs/dia) - Open-source TTS inspiration
