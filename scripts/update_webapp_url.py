#!/usr/bin/env python3
"""Update and validate WEBAPP_URL for local Telegram Web App testing."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ENV_PATH = BASE_DIR / ".env"
DEFAULT_VITE_URL = "http://127.0.0.1:5173"
DEFAULT_API_URL = "http://127.0.0.1:8080"
DEFAULT_API_PATH = "/api/user"
PINGGY_DEBUGGER_URL = "http://127.0.0.1:4300/urls"


def _normalize_argv(argv: list[str]) -> list[str]:
    """Tolerate pasting the npm wrapper after `npm run webapp:url --`."""
    if argv[:3] == ["npm", "run", "webapp:url"]:
        argv = argv[3:]
        if argv[:1] == ["--"]:
            argv = argv[1:]
    return argv


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Set WEBAPP_URL in .env to the current HTTPS tunnel URL and "
            "optionally validate the local Vite/API path."
        )
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="Current HTTPS tunnel URL, for example https://abc.run.pinggy-free.link",
    )
    parser.add_argument(
        "--env",
        default=str(DEFAULT_ENV_PATH),
        help="Path to .env file. Defaults to repo-root .env.",
    )
    parser.add_argument(
        "--from-pinggy-debugger",
        action="store_true",
        help=(
            "Read the active HTTPS URL from Pinggy debugger at "
            "http://127.0.0.1:4300/urls. Start Pinggy with "
            "'-L4300:127.0.0.1:4300' to use this."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check local Vite, public tunnel root, and public /api/user after updating.",
    )
    return parser.parse_args(_normalize_argv(sys.argv[1:]))


def _request(url: str, method: str = "HEAD", timeout: float = 8.0) -> tuple[int, str]:
    request = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.reason
    except urllib.error.HTTPError as exc:
        return exc.code, exc.reason
    except urllib.error.URLError as exc:
        return 0, str(exc.reason)
    except Exception as exc:
        return 0, str(exc)


def _load_pinggy_debugger_url() -> str:
    request = urllib.request.Request(PINGGY_DEBUGGER_URL, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=5.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise SystemExit(
            "Could not read Pinggy debugger URL. Start tunnel like this first:\n"
            "ssh -p 443 -R0:127.0.0.1:5173 -L4300:127.0.0.1:4300 a.pinggy.io\n"
            f"Reason: {exc}"
        ) from exc

    urls = payload.get("urls", [])
    https_urls = [url for url in urls if isinstance(url, str) and url.startswith("https://")]
    if not https_urls:
        raise SystemExit(f"Pinggy debugger did not return an HTTPS URL: {payload}")
    return https_urls[0]


def _normalize_webapp_url(raw_url: str) -> str:
    url = raw_url.strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise SystemExit("WEBAPP_URL must be a full HTTPS URL, for example https://abc.run.pinggy-free.link")
    return urllib.parse.urlunparse(parsed._replace(fragment=""))


def _read_current_env(env_path: Path) -> list[str]:
    if not env_path.exists():
        raise SystemExit(f"{env_path} does not exist. Create it from .env.example first.")
    return env_path.read_text(encoding="utf-8").splitlines()


def _write_webapp_url(env_path: Path, webapp_url: str) -> str | None:
    lines = _read_current_env(env_path)
    old_value: str | None = None
    updated = False
    next_lines: list[str] = []

    for line in lines:
        if line.startswith("WEBAPP_URL="):
            old_value = line.split("=", 1)[1]
            next_lines.append(f"WEBAPP_URL={webapp_url}")
            updated = True
        else:
            next_lines.append(line)

    if not updated:
        if next_lines and next_lines[-1].strip():
            next_lines.append("")
        next_lines.append(f"WEBAPP_URL={webapp_url}")

    env_path.write_text("\n".join(next_lines) + "\n", encoding="utf-8")
    return old_value


def _run_checks(webapp_url: str) -> int:
    checks = [
        ("local Vite", DEFAULT_VITE_URL, {200}),
        ("local API auth gate", urllib.parse.urljoin(DEFAULT_API_URL.rstrip("/") + "/", DEFAULT_API_PATH.lstrip("/")), {401}),
        ("public WebApp", webapp_url, {200}),
        ("public API auth gate", urllib.parse.urljoin(webapp_url.rstrip("/") + "/", DEFAULT_API_PATH.lstrip("/")), {401}),
    ]

    exit_code = 0
    failed_labels: set[str] = set()
    for label, url, expected_statuses in checks:
        status, reason = _request(url)
        expected = status in expected_statuses
        marker = "OK" if expected else "FAIL"
        expected_text = "/".join(str(value) for value in sorted(expected_statuses))
        print(f"{marker}: {label}: {status} {reason} (expected {expected_text})")
        if not expected:
            failed_labels.add(label)
            exit_code = 1

    if failed_labels:
        print("")
        if "local Vite" in failed_labels:
            print("Hint: Vite is not reachable on 127.0.0.1:5173.")
            print("Start it in a separate terminal and keep it running:")
            print("  cd plagins/cherry-charm && npm run dev")
        if "local API auth gate" in failed_labels:
            print("Hint: Python API is not reachable on 127.0.0.1:8080.")
            print("Start the bot/API in a separate terminal from the repo root and keep it running:")
            print("  uv run python main.py")
        if "public API auth gate" in failed_labels and "local API auth gate" in failed_labels:
            print("Hint: public /api/* requests will keep failing until the local Python API is running.")
        if "public WebApp" in failed_labels or (
            "public API auth gate" in failed_labels
            and "local Vite" not in failed_labels
            and "local API auth gate" not in failed_labels
        ):
            print("Hint: if local Vite is running, restart Pinggy and use the fresh HTTPS URL:")
            print("  ssh -p 443 -R0:127.0.0.1:5173 a.pinggy.io")

    return exit_code


def main() -> int:
    args = _parse_args()
    env_path = Path(args.env).expanduser().resolve()

    if args.from_pinggy_debugger:
        raw_url = _load_pinggy_debugger_url()
    elif args.url:
        raw_url = args.url
    else:
        raise SystemExit(
            "Pass the current HTTPS tunnel URL, or use --from-pinggy-debugger.\n"
            "Example: uv run python scripts/update_webapp_url.py https://abc.run.pinggy-free.link"
        )

    webapp_url = _normalize_webapp_url(raw_url)

    if args.check:
        check_status = _run_checks(webapp_url)
        if check_status != 0:
            print("WEBAPP_URL was not updated because validation failed.")
            return check_status

    old_value = _write_webapp_url(env_path, webapp_url)

    if old_value == webapp_url:
        print(f"WEBAPP_URL is already set to {webapp_url}")
    elif old_value:
        print(f"Updated WEBAPP_URL: {old_value} -> {webapp_url}")
    else:
        print(f"Added WEBAPP_URL={webapp_url}")

    print("Restart the bot after this: uv run python main.py")
    print("In Telegram, send /start again or use /refresh_menu for existing users.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
