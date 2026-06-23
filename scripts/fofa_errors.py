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
    "NOT_FOUND":      4004,
    "INVALID_PARAM":  4001,
    "INTERNAL_ERROR": 5001,
}
# fmt: on

# FOFA API 响应中可能与成功信封冲突的字段——必须在 make_success 中剔除，
# 否则 FOFA 返回的 "error": 0 (int) 会覆盖我们设置的 "error": False (bool)，
# 破坏 JSON 输出的类型一致性，导致 AI 解析异常。
_API_CONFLICT_KEYS = frozenset({"error", "errmsg", "code", "__fofa__"})


def make_error(msg: str, code: str = "INTERNAL_ERROR") -> Dict[str, Any]:
    """Build a structured error response."""
    return {"__fofa__": True, "error": True, "msg": msg, "code": ERROR_CODES.get(code, 5001)}


def make_success(**kwargs: Any) -> Dict[str, Any]:
    """Build a structured success response.

    自动剔除 FOFA API 响应中可能与信封冲突的字段（error/errmsg/code/__fofa__），
    确保输出信封的类型一致性。
    """
    result: Dict[str, Any] = {"__fofa__": True, "error": False}
    for k, v in kwargs.items():
        if k not in _API_CONFLICT_KEYS:
            result[k] = v
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
