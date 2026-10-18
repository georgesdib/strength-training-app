#!/usr/bin/env python
"""Show the effective LLM configuration, and optionally test the connection.

This is the "did I configure it correctly?" tool. It prints the settings with the API key
masked, then -- with --call -- sends one tiny prompt so a wrong base URL or model name fails
here instead of in the middle of a run.

    python tools/llm_check.py
    python tools/llm_check.py --call
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strength_coach.agents import LLMError, build_client, describe, load_settings  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--call", action="store_true", help="send one test prompt")
    parser.add_argument("--config", help="path to a settings file")
    parser.add_argument(
        "--prompt",
        default="Reply with the single word: ready",
        help="prompt used by --call",
    )
    args = parser.parse_args(argv)

    settings = load_settings(args.config)
    info = describe(settings)
    width = max(len(key) for key in info)
    print("effective LLM configuration")
    for key, value in info.items():
        print(f"  {key:<{width}}  {value}")
    print()

    if not args.call:
        print("add --call to test the connection")
        return 0

    client = build_client(settings)
    if not client.available:
        print("no model is configured; add config/llm.local.toml or set the environment")
        return 2

    try:
        response = client.complete(args.prompt)
    except LLMError as exc:
        print(f"call failed: {exc}")
        return 1

    print(f"model: {response.model}")
    print(f"tokens: {response.tokens}")
    print(f"reply: {response.text}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
