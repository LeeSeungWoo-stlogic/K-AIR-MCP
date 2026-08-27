from __future__ import annotations

import argparse


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="kair-mcp-query")
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
        help="stdio: IDE 로컬 연동(기본). http: Streamable HTTP 네트워크",
    )
    return parser.parse_args(argv)
