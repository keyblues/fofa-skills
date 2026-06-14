"""Unified error format for FOFA scripts.

Provides structured JSON error/success responses and exit codes
for clean AI-tool communication. Uses only Python stdlib.

Error code ranges:
    1xxx — API / network errors
    2xxx — Authorization / quota errors
    3xxx — Cache errors
    4xxx — Invalid parameters
    5xxx — Internal errors
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict

# fmt: off
VERSION = "0.1.0"

ERROR_CODES: Dict[str, int] = {
    "OK":                0,
    "API_ERROR":      1001,
    "AUTH_ERROR":     1002,
    "RATE_LIMIT":     1003,
    "NETWORK_ERROR":  1004,
    "FPOINT_DENIED":  2001,
    "NO_API_ACCESS":  2002,
    "QUOTA_EXCEEDED": 2003,
    "CACHE_MISS":     3001,
    "INTERNAL_ERROR": 5001,
    "INVALID_PARAM":  4001,
}
# fmt: on


def make_error(msg: str, code: str = "INTERNAL_ERROR") -> Dict[str, Any]:
    """Build a structured error response."""
    return {"__fofa__": True, "error": True, "msg": msg, "code": ERROR_CODES.get(code, 5001)}


def make_success(**kwargs: Any) -> Dict[str, Any]:
    """Build a structured success response."""
    result: Dict[str, Any] = {"__fofa__": True, "error": False}
    result.update(kwargs)
    return result


def output(result: Dict[str, Any]) -> None:
    """Write result as JSON to stdout (only JSON on stdout, nothing else)."""
    print(json.dumps(result, ensure_ascii=False))


def log(msg: str, *, level: str = "info") -> None:
    """Write diagnostic message to stderr — never to stdout (which is JSON-only)."""
    prefix = {"info": "INFO", "warn": "WARN", "error": "ERROR"}.get(level, "INFO")
    print(f"[fofa:{prefix}] {msg}", file=sys.stderr)


def die(msg: str, code: str = "INTERNAL_ERROR") -> None:
    """Print error and exit with non-zero code."""
    output(make_error(msg, code))
    sys.exit(1)
