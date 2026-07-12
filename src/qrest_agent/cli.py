from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from qrest_agent.agent.metadata_agent import MetadataAgent
from qrest_agent.core.validator import validate_metadata
from qrest_agent.llm.clients import OllamaCliClient, OllamaClient, OpenAICompatibleClient
from qrest_agent.resources import list_qrest_examples, qrest_docs_root, qrest_schema_path, qrest_tool_path
from qrest_agent.tools.qrest_data_tools import QrestDataTools


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="qrest-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="validate an existing qREST metadata JSON file")
    validate_parser.add_argument("metadata_json")

    extract_parser = subparsers.add_parser("extract-text", help="extract candidates from a text message")
    extract_parser.add_argument("text")
    extract_parser.add_argument("--provider", choices=["rule", "ollama", "ollama-cli", "openai-compatible"], default="rule")
    extract_parser.add_argument("--model", default=os.environ.get("QREST_AGENT_MODEL", "qwen3.5:4b"))
    extract_parser.add_argument("--base-url", default=os.environ.get("QREST_AGENT_BASE_URL", "http://localhost:11434"))
    extract_parser.add_argument("--api-key", default=os.environ.get("QREST_AGENT_API_KEY", ""))

    extract_file_parser = subparsers.add_parser("extract-file", help="extract candidates from a supported text file")
    extract_file_parser.add_argument("path")

    export_file_parser = subparsers.add_parser(
        "export-from-file",
        help="extract from a supported file and export metadata plus audit trail when ready",
    )
    export_file_parser.add_argument("path")
    export_file_parser.add_argument("metadata_output")
    export_file_parser.add_argument("audit_output")

    resources_parser = subparsers.add_parser("resources", help="list bundled qREST resources")
    resources_parser.add_argument("--json", action="store_true", help="print machine-readable JSON")

    generate_parser = subparsers.add_parser("generate-qrest", help="generate a .qrest file from metadata JSON and data TXT")
    generate_parser.add_argument("metadata_json")
    generate_parser.add_argument("data_txt")
    generate_parser.add_argument("output_qrest")

    load_parser = subparsers.add_parser("load-qrest", help="extract metadata JSON and data TXT from a .qrest file")
    load_parser.add_argument("input_qrest")
    load_parser.add_argument("output_metadata_json")
    load_parser.add_argument("output_data_txt")

    args = parser.parse_args(argv)
    if args.command == "validate":
        return _validate(args.metadata_json)
    if args.command == "extract-text":
        return _extract_text(args)
    if args.command == "extract-file":
        return _extract_file(args.path)
    if args.command == "export-from-file":
        return _export_from_file(args.path, args.metadata_output, args.audit_output)
    if args.command == "resources":
        return _resources(args.json)
    if args.command == "generate-qrest":
        return _generate_qrest(args.metadata_json, args.data_txt, args.output_qrest)
    if args.command == "load-qrest":
        return _load_qrest(args.input_qrest, args.output_metadata_json, args.output_data_txt)
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


def _export_from_file(path: str, metadata_output: str, audit_output: str) -> int:
    agent = MetadataAgent()
    result = agent.run_turn(files=[path])
    report = agent.export_artifacts(metadata_output, audit_output)
    payload = {
        "response": result.response,
        "report": report.to_dict(),
        "metadata_output": metadata_output if report.ready else None,
        "audit_output": audit_output,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if report.ready else 1


def _resources(as_json: bool) -> int:
    payload = {
        "examples": [str(path) for path in list_qrest_examples()],
        "docs": str(qrest_docs_root()),
        "schema": str(qrest_schema_path()),
        "tools": {
            "data_generator": str(qrest_tool_path("data_generator")),
            "data_loader": str(qrest_tool_path("data_loader")),
        },
    }
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("Bundled qREST resources")
        print(f"Docs: {payload['docs']}")
        print(f"Schema: {payload['schema']}")
        print("Examples:")
        for path in payload["examples"]:
            print(f"  - {path}")
        print("Tools:")
        for name, path in payload["tools"].items():
            print(f"  - {name}: {path}")
    return 0


def _generate_qrest(metadata_json: str, data_txt: str, output_qrest: str) -> int:
    result = QrestDataTools().generate_qrest(metadata_json, data_txt, output_qrest)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


def _load_qrest(input_qrest: str, output_metadata_json: str, output_data_txt: str) -> int:
    result = QrestDataTools().load_qrest(input_qrest, output_metadata_json, output_data_txt)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.ok else 1


def _make_client(args: argparse.Namespace) -> Any:
    if args.provider == "rule":
        return None
    if args.provider == "ollama":
        return OllamaClient(model=args.model, base_url=args.base_url)
    if args.provider == "ollama-cli":
        return OllamaCliClient(model=args.model)
    if args.provider == "openai-compatible":
        if not args.api_key:
            raise SystemExit("--api-key or QREST_AGENT_API_KEY is required")
        return OpenAICompatibleClient(model=args.model, base_url=args.base_url, api_key=args.api_key)
    raise SystemExit(f"unknown provider: {args.provider}")


if __name__ == "__main__":
    sys.exit(main())
