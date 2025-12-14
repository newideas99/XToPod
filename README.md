# Xtopod - X to Podcast Pipeline

Automatically transform your X "For You" feed into **X Digest** - a daily AI-generated podcast with NotebookLM-quality multi-speaker dialogue.

## Quick Start

### macOS
```
Double-click launch.command
```

### Windows
```
Double-click launch.bat
```

**That's it!** The script handles everything:
- Opens your browser to get API keys (takes 2 minutes)
- Guides you through X cookie setup
- Installs Python dependencies automatically
- Generates your first podcast

Your MP3 podcast will be saved to the `output/` folder.

## Requirements

- **Python 3.10+** - [Download here](https://www.python.org/downloads/)
- **OpenRouter API key** (free tier available) - [Get one here](https://openrouter.ai/keys)
- **Google API key** (free tier available) - [Get one here](https://aistudio.google.com/app/apikey)
- **X account** - You need to be logged into X in your browser

## Cost

~$8-15/month for daily podcasts (API costs only, runs on your computer)

| Component | Cost |
|-----------|------|
| LLM (Gemini via OpenRouter) | ~$2-5/mo |
| TTS (Gemini 2.5) | ~$6-12/mo |

## Features

- **Scrapes your X "For You" feed** using browser automation
- **AI analyzes posts** to find the most interesting content
- **Generates natural dialogue** between two podcast hosts
- **Creates MP3 audio** with realistic multi-speaker voices

## Troubleshooting

### "Failed to load feed - check authentication"
Your X cookies expired. Delete `cookies.json` and run the launcher again.

### "No interesting tweets found"
Run the launcher again to collect fresh tweets.

---

<details>
<summary><strong>Advanced: Manual Setup & CLI Commands</strong></summary>

### Manual Installation

```bash
git clone https://github.com/newideas99/XToPod.git
cd XToPod
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium
```

### CLI Commands

```bash
python -m src.cli quick     # Full pipeline: collect → analyze → generate
python -m src.cli collect   # Just collect tweets
python -m src.cli analyze   # Just analyze tweets
python -m src.cli generate  # Just generate podcast
python -m src.cli stats     # Show statistics
```

### Environment Variables

Copy `.env.example` to `.env` and edit:

```env
OPENROUTER_API_KEY=sk-or-v1-your-key
GOOGLE_API_KEY=your-google-key
```

### Cookie Setup (Manual)

1. Go to [x.com](https://x.com) and log in
2. Open Developer Tools (F12)
3. Go to Application → Cookies → https://x.com
4. Copy `auth_token` and `ct0` values
5. Create `cookies.json`:

```json
[
  {"name": "auth_token", "value": "YOUR_VALUE", "domain": ".x.com", "path": "/"},
  {"name": "ct0", "value": "YOUR_VALUE", "domain": ".x.com", "path": "/"}
]
```

</details>

## License

MIT License
