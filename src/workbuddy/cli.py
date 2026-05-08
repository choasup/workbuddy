import argparse
import os
import sys
from typing import Sequence

from anthropic import Anthropic

DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1024


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="workbuddy",
        description="Minimal Python CLI agent assistant backed by the Claude API.",
    )
    parser.add_argument("task", help="Natural-language task for the agent to run.")
    return parser


def _extract_text(response) -> str:
    parts = []
    for block in getattr(response, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "".join(parts)


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

    client = Anthropic(api_key=api_key)
    response = client.messages.create(
        model=DEFAULT_MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": args.task}],
    )
    print(_extract_text(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
