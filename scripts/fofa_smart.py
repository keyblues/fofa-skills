#!/usr/bin/env python3
"""FOFA Smart Query — AI-callable CLI for FOFA cyberspace search engine.

Designed as the single entry point for Claude Code and other AI agents.
Returns structured JSON summaries — never dumps full result sets into context.

Subcommands
-----------
info            Get account info (cached 5 min, free). Use --refresh to force.
search          Search FOFA with hash-based cache + F-point budget guard. Use --no-cache to skip cache.
stats           Statistical aggregation for a query (free).
host            Get detailed info about a specific host (free).
cache-read      Paginate / filter cached results by query hash.
cache-delete    Delete a single cached query by hash.
cache-export    Export cached results to JSON or CSV file.
cache-clean     Purge cache entries older than N days.
cache-stats     Show cache row counts.
audit-log       Show recent audit log entries.

Environment
-----------
FOFA_KEY            required — FOFA API key (32-char hex from personal center).
FOFA_DB_PATH        optional — SQLite path (default: ./data/fofa_cache.db).
FOFA_ALLOW_FPOINTS  optional — set "true" to globally allow F-point spend.
FOFA_BASE_URL       optional — override API base (default: https://fofa.info/api/v1).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time as _time
from datetime import datetime, timedelta
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(__file__))

import fofa_api
import fofa_cache
import fofa_errors

PREVIEW_SIZE: int = 20


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.path.join(PROJECT_ROOT, ".env")


def _load_env_file() -> Dict[str, str]:
    """Parse .env file, return dict of key-value pairs."""
    result: Dict[str, str] = {}
    if not os.path.isfile(ENV_FILE):
        return result
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                result[k.strip()] = v.strip().strip('"').strip("'")
    return result


def _get_key() -> str:
    """Get FOFA_KEY from env or .env file. Dies with AUTH_ERROR if not found."""
    key = os.environ.get("FOFA_KEY", "")
    if key:
        return key

    env_vars = _load_env_file()
    key = env_vars.get("FOFA_KEY", "")
    if key:
        os.environ["FOFA_KEY"] = key
        return key

    fofa_errors.die(
        "FOFA_KEY not configured. Create .env with FOFA_KEY=xxx or set env var. "
        "Get your key from https://fofa.info personal center.",
        "AUTH_ERROR",
    )
    return ""  # unreachable, satisfies type checker


def _validate_key(key: str) -> None:
    """Pre-validate key format: must be 32-char hex. Warn on stderr if not."""
    if not re.fullmatch(r"[0-9a-fA-F]{32}", key):
        fofa_errors.log(
            f"FOFA_KEY format warning: expected 32-char hex, got {len(key)} chars. "
            "This may cause auth errors (code 1002).",
            level="warn",
        )


def _resolve_info(key: str) -> Dict[str, Any]:
    """Get account info — cached if fresh, API otherwise."""
    cached = fofa_cache.get_info_cache()
    if cached is not None:
        return cached
    resp = fofa_api.get_info(key)
    if resp.get("error"):
        fofa_errors.die(resp.get("msg", "Account info fetch failed"), "API_ERROR")
    fofa_cache.set_info_cache(resp)
    return resp  # type: ignore[return-value]


def _parse_filter_arg(filter_str: str) -> List[Dict[str, str]]:
    """Parse ``port=443,title~Apache`` into structured filter list."""
    if not filter_str:
        return []
    filters: List[Dict[str, str]] = []
    for part in filter_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "~" in part:
            field, value = part.split("~", 1)
            filters.append({"field": field.strip(), "op": "like", "value": value.strip()})
        elif "=" in part:
            field, value = part.split("=", 1)
            filters.append({"field": field.strip(), "op": "eq", "value": value.strip()})
    return filters


def _error_code_to_int(resp: Dict[str, Any]) -> int:
    """Extract numeric error code from a response, return 0 if success."""
    if not resp.get("error"):
        return 0
    return resp.get("code", 1)


# ------------------------------------------------------------------ commands


def cmd_info(args: argparse.Namespace) -> None:
    """Print account info (cached 5 min, use --refresh to force)."""
    t0 = _time.monotonic()
    key = _get_key()
    _validate_key(key)

    if not args.refresh:
        cached = fofa_cache.get_info_cache()
        if cached is not None:
            fofa_errors.output(fofa_errors.make_success(from_cache=True, **cached))
            fofa_cache.log_audit("info", result_code=0, duration_ms=int((_time.monotonic() - t0) * 1000))
            return

    resp = fofa_api.get_info(key)
    code = _error_code_to_int(resp)
    if resp.get("error"):
        fofa_cache.log_audit("info", result_code=code, duration_ms=int((_time.monotonic() - t0) * 1000))
        fofa_errors.die(resp.get("msg", "Account info fetch failed"), "API_ERROR")

    fofa_cache.set_info_cache(resp)
    fofa_errors.output(fofa_errors.make_success(from_cache=False, **resp))
    fofa_cache.log_audit("info", result_code=0, duration_ms=int((_time.monotonic() - t0) * 1000))


def cmd_search(args: argparse.Namespace) -> None:
    """Search FOFA — hash-based cache, F-point guard, summary-only output."""
    t0 = _time.monotonic()
    key = _get_key()
    _validate_key(key)

    info = _resolve_info(key)
    # Use `is False` to distinguish "registered user (isvip=false)" from "unknown (None)"
    if info.get("isvip") is False:
        fofa_cache.log_audit("search", query_raw=args.query,
                             params={"fields": args.fields, "page": args.page, "size": args.size},
                             result_code=2002, duration_ms=int((_time.monotonic() - t0) * 1000))
        fofa_errors.die("Registered user — no API access. Upgrade required.", "NO_API_ACCESS")

    allow_fpoints = args.allow_fpoints or os.environ.get("FOFA_ALLOW_FPOINTS", "") == "true"

    if args.size < 1 or args.size > 10000:
        fofa_cache.log_audit("search", query_raw=args.query,
                             params={"size": args.size},
                             result_code=4001, duration_ms=int((_time.monotonic() - t0) * 1000))
        fofa_errors.die(f"size out of range (1-10000), got {args.size}", "INVALID_PARAM")

    query_hash = fofa_cache.hash_query(args.query, args.fields, args.full, args.page, args.size)

    # --- cache hit (skip if --no-cache) ---
    cached = None if args.no_cache else fofa_cache.lookup(query_hash)
    if cached is not None:
        results_data = fofa_cache.read(query_hash, page=1, size=PREVIEW_SIZE)
        fofa_errors.output(fofa_errors.make_success(
            from_cache=True,
            query_hash=query_hash,
            query_raw=args.query,
            fields=args.fields,
            full=args.full,
            page=args.page,
            size=args.size,
            total=cached["total"],
            preview=results_data["results"],
            fpoints_consumed=0,
        ))
        fofa_cache.log_audit("search", query_hash=query_hash, query_raw=args.query,
                             result_code=0, duration_ms=int((_time.monotonic() - t0) * 1000))
        return

    # --- covering cache: reuse page-1 data for page>1 requests ---
    if args.page > 1 and not args.no_cache:
        covering = fofa_cache.find_covering_cache(
            args.query, args.fields, args.full, args.page, args.size
        )
        if covering is not None:
            data = fofa_cache.read(covering["query_hash"], page=args.page, size=args.size)
            fofa_errors.output(fofa_errors.make_success(
                from_cache=True,
                query_hash=covering["query_hash"],
                query_raw=args.query,
                fields=args.fields,
                full=args.full,
                page=args.page,
                size=args.size,
                total=covering["total"],
                preview=data["results"][:PREVIEW_SIZE],
                fpoints_consumed=0,
                covering_cache=True,
            ))
            fofa_cache.log_audit("search", query_hash=covering["query_hash"], query_raw=args.query,
                                 params={"covering_cache": True, "page": args.page},
                                 result_code=0, duration_ms=int((_time.monotonic() - t0) * 1000))
            return

    # --- API call ---
    resp = fofa_api.search(
        key, args.query,
        fields=args.fields,
        page=args.page,
        size=args.size,
        full=args.full,
        allow_fpoints=allow_fpoints,
    )

    code = _error_code_to_int(resp)
    if resp.get("error"):
        fofa_cache.log_audit("search", query_hash=query_hash, query_raw=args.query,
                             params={"page": args.page, "size": args.size},
                             result_code=code, duration_ms=int((_time.monotonic() - t0) * 1000))
        fofa_errors.die(resp.get("msg", "FOFA API query failed"), "API_ERROR")

    raw_results = resp.get("results", [])
    fields_list = [f.strip() for f in args.fields.split(",")]
    results: List[Dict[str, Any]] = []
    
    for row in raw_results:
        # FOFA API typically returns List[List], but we handle dict just in case
        if isinstance(row, list):
            results.append(dict(zip(fields_list, row)))
        elif isinstance(row, dict):
            results.append(row)
        else:
            results.append({"_raw": row})

    total: int = resp.get("size", 0)

    fofa_cache.save(query_hash, args.query, args.fields, args.full,
                    args.page, args.size, total, results)

    preview = results[:PREVIEW_SIZE]
    fpoints_cost = 0 if args.page <= 1 else (args.page - 1) * args.size  # estimated, not server-confirmed

    fofa_errors.output(fofa_errors.make_success(
        from_cache=False,
        query_hash=query_hash,
        query_raw=args.query,
        fields=args.fields,
        full=args.full,
        page=args.page,
        size=args.size,
        total=total,
        preview=preview,
        fpoints_consumed=fpoints_cost,
    ))
    fofa_cache.log_audit("search", query_hash=query_hash, query_raw=args.query,
                         params={"page": args.page, "size": args.size, "full": args.full},
                         result_code=0, duration_ms=int((_time.monotonic() - t0) * 1000))


def cmd_cache_read(args: argparse.Namespace) -> None:
    """Read cached results with optional filtering."""
    t0 = _time.monotonic()
    filters = _parse_filter_arg(args.filter)
    cached = fofa_cache.lookup(args.hash, allow_expired=True)
    if cached is None:
        fofa_cache.log_audit("cache-read", query_hash=args.hash,
                             result_code=3001, duration_ms=int((_time.monotonic() - t0) * 1000))
        fofa_errors.die(f"Cache miss: {args.hash}", "CACHE_MISS")

    # Check if cache has expired — still return data but warn the user
    cache_expired = False
    if cached.get("expires_at"):
        try:
            expires = datetime.strptime(cached["expires_at"], "%Y-%m-%d %H:%M:%S")
            cache_expired = datetime.now() > expires
        except (ValueError, TypeError):
            pass

    data = fofa_cache.read(
        args.hash,
        filters=filters if filters else None,
        page=args.page,
        size=args.size,
    )

    fofa_errors.output(fofa_errors.make_success(
        query_hash=args.hash,
        query_raw=cached["query_raw"],
        total=data["total"],
        page=data["page"],
        size=data["size"],
        results=data["results"],
        cache_expired=cache_expired,
    ))
    fofa_cache.log_audit("cache-read", query_hash=args.hash,
                         query_raw=cached.get("query_raw"),
                         params={"page": args.page, "size": args.size, "filter": args.filter},
                         result_code=0, duration_ms=int((_time.monotonic() - t0) * 1000))


def cmd_cache_clean(args: argparse.Namespace) -> None:
    """Purge cache entries older than N days."""
    t0 = _time.monotonic()
    cutoff = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d %H:%M:%S")
    deleted = fofa_cache.clean(cutoff)
    fofa_errors.output(fofa_errors.make_success(deleted=deleted, cutoff=cutoff))
    fofa_cache.log_audit("cache-clean", params={"days": args.days, "cutoff": cutoff},
                         result_code=0, duration_ms=int((_time.monotonic() - t0) * 1000))


def cmd_cache_stats(_args: argparse.Namespace) -> None:
    """Print cache row counts."""
    t0 = _time.monotonic()
    stats = fofa_cache.cache_stats()
    fofa_errors.output(fofa_errors.make_success(**stats))
    fofa_cache.log_audit("cache-stats", result_code=0, duration_ms=int((_time.monotonic() - t0) * 1000))


def cmd_stats(args: argparse.Namespace) -> None:
    """Run statistical aggregation on a FOFA query."""
    t0 = _time.monotonic()
    key = _get_key()
    _validate_key(key)
    resp = fofa_api.stats(key, args.query, args.field)
    code = _error_code_to_int(resp)
    if resp.get("error"):
        fofa_cache.log_audit("stats", query_raw=args.query,
                             params={"field": args.field},
                             result_code=code, duration_ms=int((_time.monotonic() - t0) * 1000))
        fofa_errors.die(resp.get("msg", "Stats query failed"), "API_ERROR")
    fofa_errors.output(fofa_errors.make_success(**resp))
    fofa_cache.log_audit("stats", query_raw=args.query,
                         params={"field": args.field},
                         result_code=0, duration_ms=int((_time.monotonic() - t0) * 1000))


def cmd_host(args: argparse.Namespace) -> None:
    """Get detailed info about a specific host."""
    t0 = _time.monotonic()
    key = _get_key()
    _validate_key(key)
    resp = fofa_api.host(key, args.host, args.detail)
    code = _error_code_to_int(resp)
    if resp.get("error"):
        fofa_cache.log_audit("host", params={"host": args.host, "detail": args.detail},
                             result_code=code, duration_ms=int((_time.monotonic() - t0) * 1000))
        fofa_errors.die(resp.get("msg", "Host query failed"), "API_ERROR")
    fofa_errors.output(fofa_errors.make_success(**resp))
    fofa_cache.log_audit("host", params={"host": args.host, "detail": args.detail},
                         result_code=0, duration_ms=int((_time.monotonic() - t0) * 1000))


def cmd_cache_delete(args: argparse.Namespace) -> None:
    """Delete a single cached query by hash."""
    t0 = _time.monotonic()
    deleted = fofa_cache.delete_cache(args.hash)
    if not deleted:
        fofa_cache.log_audit("cache-delete", query_hash=args.hash,
                             result_code=3001, duration_ms=int((_time.monotonic() - t0) * 1000))
        fofa_errors.die(f"Cache miss: {args.hash}", "CACHE_MISS")
    fofa_errors.output(fofa_errors.make_success(deleted=True, query_hash=args.hash))
    fofa_cache.log_audit("cache-delete", query_hash=args.hash,
                         result_code=0, duration_ms=int((_time.monotonic() - t0) * 1000))


def cmd_cache_export(args: argparse.Namespace) -> None:
    """Export cached results to a file."""
    t0 = _time.monotonic()
    cached = fofa_cache.lookup(args.hash, allow_expired=True)
    if cached is None:
        fofa_cache.log_audit("cache-export", query_hash=args.hash,
                             result_code=3001, duration_ms=int((_time.monotonic() - t0) * 1000))
        fofa_errors.die(f"Cache miss: {args.hash}", "CACHE_MISS")

    # Check if cache has expired
    cache_expired = False
    if cached.get("expires_at"):
        try:
            expires = datetime.strptime(cached["expires_at"], "%Y-%m-%d %H:%M:%S")
            cache_expired = datetime.now() > expires
        except (ValueError, TypeError):
            pass

    result = fofa_cache.export_cache(args.hash, fmt=args.format, output_path=args.output)
    fofa_errors.output(fofa_errors.make_success(**result, cache_expired=cache_expired))
    fofa_cache.log_audit("cache-export", query_hash=args.hash,
                         params={"format": args.format, "output": args.output},
                         result_code=0, duration_ms=int((_time.monotonic() - t0) * 1000))


def cmd_audit_log(args: argparse.Namespace) -> None:
    """Show recent audit log entries."""
    t0 = _time.monotonic()
    entries = fofa_cache.read_audit_log(limit=args.limit, command=args.command)
    fofa_errors.output(fofa_errors.make_success(
        total=len(entries),
        entries=entries,
    ))
    # Don't audit the audit-log command itself to avoid recursion noise


# ------------------------------------------------------------------ CLI


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser."""
    parser = argparse.ArgumentParser(
        description="FOFA Smart Query — AI-callable search with caching and F-point guard",
    )
    parser.add_argument("--version", action="version", version=f"fofa-skills {fofa_errors.VERSION}")
    sub = parser.add_subparsers(dest="command")

    # info
    p = sub.add_parser("info", help="Get account info (cached 5 min)")
    p.add_argument("--refresh", action="store_true", help="Force refresh, ignore cache")

    # search
    p = sub.add_parser("search", help="Search FOFA assets (summary only)")
    p.add_argument("--query", "-q", required=True, help="FOFA query string")
    p.add_argument("--fields", "-f", default="ip,port,protocol,host,domain,title,server",
                   help="Return fields, comma-separated")
    p.add_argument("--page", "-p", type=int, default=1, help="Page number (default 1)")
    p.add_argument("--size", "-s", type=int, default=100, help="Page size (default 100, max 10000)")
    p.add_argument("--full", action="store_true", help="Search all historical data (default: recent year)")
    p.add_argument("--no-cache", action="store_true", help="Skip cache, force fresh query")
    p.add_argument("--allow-fpoints", action="store_true",
                   help="Allow F-point spend for pagination (only with explicit user authorization)")

    # cache-read
    p = sub.add_parser("cache-read", help="Read cached results (paginate/filter)")
    p.add_argument("--hash", required=True, help="Query hash from search result's query_hash")
    p.add_argument("--filter", default="", help="Filter: field=value (exact), field~value (fuzzy), comma-separated")
    p.add_argument("--page", "-p", type=int, default=1, help="Page number")
    p.add_argument("--size", "-s", type=int, default=100, help="Page size")

    # cache-delete
    p = sub.add_parser("cache-delete", help="Delete a cached query by hash")
    p.add_argument("--hash", required=True, help="Query hash to delete")

    # cache-export
    p = sub.add_parser("cache-export", help="Export cached results to file")
    p.add_argument("--hash", required=True, help="Query hash")
    p.add_argument("--format", "-f", default="json", choices=["json", "csv"], help="Export format (default json)")
    p.add_argument("--output", "-o", default=None, help="Output file path; auto-generated under data/ if omitted")

    # cache-clean
    p = sub.add_parser("cache-clean", help="Purge cache entries older than N days")
    p.add_argument("--days", "-d", type=int, default=30, help="Keep last N days (default 30)")

    # stats
    p = sub.add_parser("stats", help="Statistical aggregation (free)")
    p.add_argument("--query", "-q", required=True, help="FOFA query string")
    p.add_argument("--field", "-f", required=True, help="Aggregation field(s), e.g. country, port, protocol. Comma-separated for multi-field aggregation")

    # host
    p = sub.add_parser("host", help="Host details (free)")
    p.add_argument("--host", required=True, help="Target IP or domain")
    p.add_argument("--detail", action="store_true", help="Include port/protocol/cert details")

    # cache-stats
    sub.add_parser("cache-stats", help="Show cache row counts")

    # audit-log
    p = sub.add_parser("audit-log", help="Show recent audit log entries")
    p.add_argument("--limit", "-n", type=int, default=50, help="Max entries to return (default 50)")
    p.add_argument("--command", "-c", default=None, help="Filter by command name (e.g. search, info)")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    fofa_cache.init_db()

    commands = {
        "info": cmd_info,
        "search": cmd_search,
        "stats": cmd_stats,
        "host": cmd_host,
        "cache-read": cmd_cache_read,
        "cache-delete": cmd_cache_delete,
        "cache-export": cmd_cache_export,
        "cache-clean": cmd_cache_clean,
        "cache-stats": cmd_cache_stats,
        "audit-log": cmd_audit_log,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
