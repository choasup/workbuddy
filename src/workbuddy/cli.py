import argparse
from typing import Sequence


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="workbuddy",
        description="Minimal Python CLI agent assistant backed by the Claude API.",
    )
    parser.add_argument("task", help="Natural-language task for the agent to run.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    print(args.task)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
