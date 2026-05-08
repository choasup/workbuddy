import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from anthropic import Anthropic, APIError

DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1024
MAX_LOGGED_RESPONSE_CHARS = 4000
REQUEST_TIMEOUT_SECONDS = 60.0


def _config_path() -> Path:
    return _log_path().parent / "config.json"


def _load_config_default_model() -> str:
    path = _config_path()
    if not path.exists():
        return DEFAULT_MODEL
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"warning: ignoring malformed config.json: {exc}", file=sys.stderr)
        return DEFAULT_MODEL
    if not isinstance(data, dict):
        print(
            "warning: ignoring malformed config.json: top-level must be an object",
            file=sys.stderr,
        )
        return DEFAULT_MODEL
    value = data.get("default_model")
    if isinstance(value, str) and value:
        return value
    print(
        "warning: ignoring malformed config.json: default_model must be a non-empty string",
        file=sys.stderr,
    )
    return DEFAULT_MODEL


def _build_parser() -> argparse.ArgumentParser:
    effective_default = _load_config_default_model()
    parser = argparse.ArgumentParser(
        prog="workbuddy",
        description="Minimal Python CLI agent assistant backed by the Claude API.",
    )
    parser.add_argument("task", help="Natural-language task for the agent to run.")
    parser.add_argument(
        "--model",
        default=effective_default,
        help=f"Claude model id (default: {effective_default})",
    )
    return parser


def _extract_text(response) -> str:
    parts = []
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "".join(parts)


def _log_path() -> Path:
    home_override = os.environ.get("WORKBUDDY_HOME")
    base = Path(home_override) if home_override else Path.home() / ".workbuddy"
    return base / "log.md"


def _log_run(task: str, response_text: str) -> None:
    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        body = response_text
        if len(body) > MAX_LOGGED_RESPONSE_CHARS:
            body = body[:MAX_LOGGED_RESPONSE_CHARS] + "... [truncated]"
        entry = (
            f"## {timestamp}\n"
            f"**Task:** {task}\n\n"
            f"**Response:**\n\n"
            f"{body}\n\n"
        )
        with path.open("a", encoding="utf-8") as f:
            f.write(entry)
    except OSError as exc:
        print(f"warning: failed to append run to log: {exc}", file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "error: ANTHROPIC_API_KEY environment variable is not set",
            file=sys.stderr,
        )
        return 1

    client = Anthropic(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS)
    try:
        response = client.messages.create(
            model=args.model,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": args.task}],
        )
    except APIError as exc:
        print(
            f"error: API call failed: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 2
    text = _extract_text(response)
    print(text)
    _log_run(args.task, text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
