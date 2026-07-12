from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from qrest_agent.agent.metadata_agent import MetadataAgent
from qrest_agent.core.validator import validate_metadata
from qrest_agent.llm.clients import OllamaClient, OpenAICompatibleClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qrest-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="validate an existing qREST metadata JSON file")
    validate_parser.add_argument("metadata_json")

    extract_parser = subparsers.add_parser("extract-text", help="extract candidates from a text message")
    extract_parser.add_argument("text")
    extract_parser.add_argument("--provider", choices=["rule", "ollama", "openai-compatible"], default="rule")
    extract_parser.add_argument("--model", default=os.environ.get("QREST_AGENT_MODEL", "qwen3.5:4b"))
    extract_parser.add_argument("--base-url", default=os.environ.get("QREST_AGENT_BASE_URL", "http://localhost:11434"))
    extract_parser.add_argument("--api-key", default=os.environ.get("QREST_AGENT_API_KEY", ""))

    extract_file_parser = subparsers.add_parser("extract-file", help="extract candidates from a supported text file")
    extract_file_parser.add_argument("path")

    args = parser.parse_args(argv)
    if args.command == "validate":
        return _validate(args.metadata_json)
    if args.command == "extract-text":
        return _extract_text(args)
    if args.command == "extract-file":
        return _extract_file(args.path)
    return 2


def _validate(path: str) -> int:
    metadata = json.loads(Path(path).read_text(encoding="utf-8"))
    report = validate_metadata(metadata)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if report.ready else 1


def _extract_text(args: argparse.Namespace) -> int:
    agent = MetadataAgent(llm_client=_make_client(args))
    result = agent.run_turn(text=args.text)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _extract_file(path: str) -> int:
    agent = MetadataAgent()
    result = agent.run_turn(files=[path])
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _make_client(args: argparse.Namespace) -> Any:
    if args.provider == "rule":
        return None
    if args.provider == "ollama":
        return OllamaClient(model=args.model, base_url=args.base_url)
    if args.provider == "openai-compatible":
        if not args.api_key:
            raise SystemExit("--api-key or QREST_AGENT_API_KEY is required")
        return OpenAICompatibleClient(model=args.model, base_url=args.base_url, api_key=args.api_key)
    raise SystemExit(f"unknown provider: {args.provider}")


if __name__ == "__main__":
    sys.exit(main())

