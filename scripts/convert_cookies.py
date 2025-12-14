#!/usr/bin/env python3
"""
Convert cookies.txt (Netscape format) to cookies.json (Playwright format).

Usage:
    python3 scripts/convert_cookies.py [input_file] [output_file]

    Default input: cookies.txt
    Default output: cookies.json
"""

import json
import sys
from pathlib import Path


def parse_netscape_cookies(content: str) -> list[dict]:
    """Parse Netscape cookie format (cookies.txt) into a list of cookie dicts."""
    cookies = []

    for line in content.strip().split('\n'):
        # Skip comments and empty lines
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        # Parse tab-separated fields
        # Format: domain, include_subdomains, path, secure, expiry, name, value
        parts = line.split('\t')
        if len(parts) < 7:
            continue

        domain, include_subdomains, path, secure, expiry, name, value = parts[:7]

        # Only include Twitter/X cookies
        if 'twitter.com' not in domain and 'x.com' not in domain:
            continue

        cookie = {
            'name': name,
            'value': value,
            'domain': domain,
            'path': path,
            'secure': secure.upper() == 'TRUE',
            'httpOnly': True,  # Assume httpOnly for auth cookies
        }

        # Add expiry if present and valid
        try:
            exp = int(expiry)
            if exp > 0:
                cookie['expires'] = exp
        except ValueError:
            pass

        cookies.append(cookie)

    return cookies


def main():
    # Get input/output paths from args or use defaults
    input_file = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('cookies.txt')
    output_file = Path(sys.argv[2]) if len(sys.argv) > 2 else Path('cookies.json')

    # Check input file exists
    if not input_file.exists():
        print(f"Error: Input file '{input_file}' not found.")
        print()
        print("To get cookies.txt:")
        print("1. Install 'Get cookies.txt LOCALLY' browser extension")
        print("2. Go to x.com and make sure you're logged in")
        print("3. Click the extension and export cookies")
        print("4. Save as 'cookies.txt' in this folder")
        sys.exit(1)

    # Parse cookies
    content = input_file.read_text()
    cookies = parse_netscape_cookies(content)

    if not cookies:
        print("Error: No Twitter/X cookies found in the file.")
        print("Make sure you exported cookies while on x.com or twitter.com")
        sys.exit(1)

    # Find important cookies
    cookie_names = {c['name'] for c in cookies}
    required = {'auth_token', 'ct0'}
    missing = required - cookie_names

    if missing:
        print(f"Warning: Missing required cookies: {missing}")
        print("Authentication may not work correctly.")
        print()

    # Save as JSON
    output_file.write_text(json.dumps(cookies, indent=2))

    print(f"Converted {len(cookies)} cookies to {output_file}")
    print()
    print("Cookies found:")
    for cookie in cookies:
        name = cookie['name']
        value_preview = cookie['value'][:20] + '...' if len(cookie['value']) > 20 else cookie['value']
        marker = " (required)" if name in required else ""
        print(f"  - {name}: {value_preview}{marker}")

    print()
    print("Done! You can now run the pipeline.")


if __name__ == '__main__':
    main()
