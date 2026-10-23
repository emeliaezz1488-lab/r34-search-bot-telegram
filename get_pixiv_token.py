#!/usr/bin/env python3
"""
Pixiv OAuth Refresh Token Helper

Utility to generate, refresh, or verify Pixiv OAuth refresh tokens for pixivpy3.
Supports standard OAuth PKCE manual flow (works in any terminal) and token verification.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from webbrowser import open as open_url

try:
    import requests
except ImportError:
    print("Error: The 'requests' library is required. Install it using: pip install requests")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).resolve().parent
ENV_FILE = SCRIPT_DIR / ".env"
TOKEN_FILE = SCRIPT_DIR / "token.txt"

# Official Pixiv OAuth mobile client constants
CLIENT_ID = "MOBrBDS8rwYda9n0Z/gkVUdaBmac"
CLIENT_SECRET = "lsACyCD94FhDUtGTXi3QzcFE2uU1hqt0K"
AUTH_TOKEN_URL = "https://oauth.secure.pixiv.net/auth/token"
LOGIN_URL = "https://app-api.pixiv.net/web/v1/login"
CALLBACK_URI = "https://app-api.pixiv.net/web/v1/users/auth/pixiv/callback"
USER_AGENT = "PixivAndroidApp/5.0.234 (Android 11; Pixel 5)"


def generate_pkce() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge according to RFC 7636."""
    code_verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return code_verifier, code_challenge


def parse_oauth_code(raw: str) -> str:
    """Extract authorization code from full callback URL or raw string."""
    raw = raw.strip()
    if not raw:
        raise ValueError("Empty authorization code provided.")

    if raw.startswith("http://") or raw.startswith("https://") or raw.startswith("pixiv://"):
        parsed = urlparse(raw)
        qs = parse_qs(parsed.query)
        if "code" in qs and qs["code"]:
            return unquote(qs["code"][0])

    match = re.search(r"[?&]code=([^&\s#]+)", raw)
    if match:
        return unquote(match.group(1))

    return unquote(raw)


def exchange_code_for_token(code: str, code_verifier: str) -> dict:
    """Exchange authorization code and code_verifier for refresh_token."""
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
        "code_verifier": code_verifier,
        "grant_type": "authorization_code",
        "include_policy": "true",
        "redirect_uri": CALLBACK_URI,
    }
    headers = {
        "User-Agent": USER_AGENT,
        "App-OS": "android",
        "App-OS-Version": "11",
    }
    response = requests.post(AUTH_TOKEN_URL, data=payload, headers=headers, timeout=30)
    try:
        data = response.json()
    except Exception:
        print(f"Server response ({response.status_code}): {response.text}")
        sys.exit(1)

    if response.status_code != 200 or "error" in data:
        print("Error from Pixiv OAuth service:")
        print(data)
        sys.exit(1)

    return data


def refresh_existing_token(token: str) -> dict:
    """Exchange an existing refresh_token for a fresh access and refresh token pair."""
    payload = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "refresh_token",
        "refresh_token": token.strip(),
        "include_policy": "true",
    }
    headers = {
        "User-Agent": USER_AGENT,
        "App-OS": "android",
        "App-OS-Version": "11",
    }
    response = requests.post(AUTH_TOKEN_URL, data=payload, headers=headers, timeout=30)
    try:
        data = response.json()
    except Exception:
        print(f"Server response ({response.status_code}): {response.text}")
        sys.exit(1)

    if response.status_code != 200 or "error" in data:
        print("Error refreshing token:")
        print(data)
        sys.exit(1)

    return data


def save_token_to_env(token: str) -> bool:
    """Update or append PIXIV_REFRESH_TOKEN in .env file."""
    if not ENV_FILE.exists():
        ENV_FILE.write_text(f"PIXIV_REFRESH_TOKEN={token}\n", encoding="utf-8")
        print(f"Created {ENV_FILE} and saved PIXIV_REFRESH_TOKEN.")
        return True

    content = ENV_FILE.read_text(encoding="utf-8")
    pattern = r"^PIXIV_REFRESH_TOKEN=.*$"
    if re.search(pattern, content, flags=re.MULTILINE):
        new_content = re.sub(pattern, f"PIXIV_REFRESH_TOKEN={token}", content, flags=re.MULTILINE)
    else:
        new_content = content.rstrip() + f"\nPIXIV_REFRESH_TOKEN={token}\n"

    ENV_FILE.write_text(new_content, encoding="utf-8")
    print(f"Updated PIXIV_REFRESH_TOKEN in {ENV_FILE}")
    return True


def check_token(token: str) -> bool:
    """Verify that the token can successfully authenticate with Pixiv API."""
    try:
        from pixivpy3 import AppPixivAPI
    except ImportError:
        print("Error: pixivpy3 is not installed. Install with: pip install pixivpy3")
        return False

    api = AppPixivAPI()
    try:
        api.auth(refresh_token=token.strip())
        res = api.search_illust("anime", search_target="partial_match_for_tags")
        if res and hasattr(res, "illusts") and len(res.illusts) > 0:
            sample = res.illusts[0]
            print(f"Token verification successful. Sample illust: #{sample.id} - {sample.title}")
            return True
        else:
            print("Token accepted, but search returned empty results.")
            return True
    except Exception as e:
        print(f"Token verification failed: {e}")
        return False


def run_interactive_login(save_to_env: bool = True) -> str:
    """Execute standard OAuth PKCE flow via user browser."""
    code_verifier, code_challenge = generate_pkce()
    params = {
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "client": "pixiv-android",
    }
    url = f"{LOGIN_URL}?{urlencode(params)}"

    print("=" * 60)
    print("Pixiv OAuth Token Generator")
    print("=" * 60)
    print("1. Open the following URL in your web browser (or it will open automatically):")
    print(f"\n{url}\n")
    try:
        open_url(url)
    except Exception:
        pass

    print("2. Log into your Pixiv account.")
    print("3. After login, you will be redirected to a blank/callback page (or app prompt).")
    print("   Open DevTools (F12) -> Network tab -> look for the request containing 'code='")
    print("   or copy the final URL / code parameter from the address bar.")
    print("=" * 60)

    try:
        raw_input = input("\nPaste the callback URL or authorization code here: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nOperation cancelled by user.")
        sys.exit(130)

    code = parse_oauth_code(raw_input)
    print("\nExchanging code for tokens...")
    data = exchange_code_for_token(code, code_verifier)

    refresh_token = data.get("refresh_token")
    if not refresh_token:
        print("Error: No refresh_token found in response.")
        print(data)
        sys.exit(1)

    print("\n" + "=" * 60)
    print("SUCCESS: Pixiv Refresh Token obtained!")
    print(f"PIXIV_REFRESH_TOKEN={refresh_token}")
    print("=" * 60)

    if save_to_env:
        save_token_to_env(refresh_token)

    return refresh_token


def main():
    parser = argparse.ArgumentParser(description="Pixiv OAuth Refresh Token Helper")
    parser.add_argument("--check", metavar="TOKEN", nargs="?", const="", help="Verify an existing refresh token")
    parser.add_argument("--refresh", metavar="TOKEN", help="Refresh an existing token and print the new pair")
    parser.add_argument("--no-save", action="store_true", help="Do not write token to .env file")

    args = parser.parse_args()

    if args.check is not None:
        target_token = args.check.strip()
        if not target_token and ENV_FILE.exists():
            # Try to read from .env
            content = ENV_FILE.read_text(encoding="utf-8")
            match = re.search(r"^PIXIV_REFRESH_TOKEN=(.+)$", content, flags=re.MULTILINE)
            if match:
                target_token = match.group(1).strip()
        if not target_token:
            print("Error: Please provide a token to check: python get_pixiv_token.py --check <TOKEN>")
            sys.exit(1)
        check_token(target_token)
        return

    if args.refresh:
        res = refresh_existing_token(args.refresh)
        new_token = res.get("refresh_token")
        print(f"New refresh_token: {new_token}")
        if not args.no_save and new_token:
            save_token_to_env(new_token)
        return

    run_interactive_login(save_to_env=not args.no_save)


if __name__ == "__main__":
    main()
