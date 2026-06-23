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
cache-clean     Purge cache entries older than N days.
cache-stats     Show cache row counts.
cache-list      List cached queries — recover hashes for correlate/report.
cache-tag       Tag (or re-tag) an already-cached query — group untagged searches.
correlate       Cross-query correlation & de-duplication by key field (--hashes or --tag).
report          Generate aggregated summary report across cached queries (--hashes or --tag).
audit-log       Show recent audit log entries.
audit-clean     Purge audit log entries older than N days.

Environment
-----------
FOFA_KEY            required — FOFA API key (32-char hex from personal center).
FOFA_DB_PATH        optional — SQLite path (default: ./data/fofa_cache.db).
FOFA_ALLOW_FPOINTS  optional — set "true" to globally allow F-point spend.
FOFA_FPOINTS_BUDGET optional — session-level F-point budget (e.g. 1000) to avoid per-request confirmation.
FOFA_BASE_URL       optional — override API base (default: https://fofa.info/api/v1).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import time as _time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

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


def _resolve_info(key: str, *, force_refresh: bool = False, audit_command: Optional[str] = None) -> Dict[str, Any]:
    """Get account info — cached if fresh, API otherwise.

    When ``audit_command`` is provided, an audit-log row is recorded with the
    measured duration and result code. This lets both the implicit ``info``
    lookup done by ``search`` and the explicit ``info`` subcommand share one
    implementation without duplicating audit logic.

    返回的 dict 包含内部字段 ``_from_cache``，调用方应在输出前用 ``pop`` 取出。
    """
    t0 = _time.monotonic()
    if not force_refresh:
        cached = fofa_cache.get_info_cache()
        if cached is not None:
            if audit_command:
                fofa_cache.log_audit(audit_command, result_code=0,
                                     duration_ms=int((_time.monotonic() - t0) * 1000))
            cached["_from_cache"] = True
            return cached

    resp = fofa_api.get_info(key)
    code = _error_code_to_int(resp)
    if resp.get("error"):
        if audit_command:
            fofa_cache.log_audit(audit_command, result_code=code,
                                 duration_ms=int((_time.monotonic() - t0) * 1000))
        fofa_errors.die(resp.get("msg", "Account info fetch failed"), "API_ERROR")

    fofa_cache.set_info_cache(resp)
    if audit_command:
        fofa_cache.log_audit(audit_command, result_code=code,
                             duration_ms=int((_time.monotonic() - t0) * 1000))
    resp["_from_cache"] = False
    return resp


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


def _is_cache_expired(cached: Dict[str, Any]) -> bool:
    """Check if a cache entry has expired based on its expires_at field.

    expires_at 缺失或格式异常时返回 False（fail-open），
    避免格式异常导致可用缓存被误判为过期。
    """
    if not cached.get("expires_at"):
        return False
    try:
        expires = datetime.strptime(cached["expires_at"], "%Y-%m-%d %H:%M:%S")
        return datetime.now() > expires
    except (ValueError, TypeError):
        return False


def _resolve_hashes(args: argparse.Namespace) -> List[str]:
    """Resolve a hash list from either ``--hashes`` or ``--tag``.

    When ``--tag`` is given it takes precedence and expands to all queries in
    that assessment target. If ``--hashes`` was also supplied, emit a stderr
    warning so the caller knows it was ignored (silent override is a foot-gun:
    an AI passing ``--tag acme.com --hashes h_extra`` would silently lose h_extra).
    This is the AI's recovery path: even after context compression wipes the
    in-memory hash list, ``--tag acme.com`` still finds every cached query for
    that target without a re-fetch.
    """
    tag = getattr(args, "tag", None)
    raw = getattr(args, "hashes", None) or ""
    explicit_hashes = [h.strip() for h in raw.split(",") if h.strip()]
    if tag:
        if explicit_hashes:
            sys.stderr.write(
                f"[fofa] warning: --tag '{tag}' takes precedence; "
                f"ignoring {len(explicit_hashes)} --hashes value(s).\n"
            )
        hashes = fofa_cache.resolve_tag_to_hashes(tag)
        if not hashes:
            fofa_errors.die(f"no cached queries found with tag '{tag}'", "NOT_FOUND")
        return hashes
    return explicit_hashes


def _parse_int_list(raw: str, label: str) -> tuple:
    """Parse a comma-separated int list (e.g. '22,23,3389'). Dies on bad input."""
    out: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            fofa_errors.die(f"invalid {label} value '{part}' (expected integer)", "INVALID_PARAM")
    if not out:
        fofa_errors.die(f"--{label} requires at least one value", "INVALID_PARAM")
    return tuple(out)


# ------------------------------------------------------------------ commands


def cmd_info(args: argparse.Namespace) -> None:
    """Print account info (cached 5 min, use --refresh to force)."""
    key = _get_key()
    _validate_key(key)

    resp = _resolve_info(key, force_refresh=args.refresh, audit_command="info")
    from_cache = resp.pop("_from_cache", False)
    fofa_errors.output(fofa_errors.make_success(from_cache=from_cache, **resp))


def cmd_search(args: argparse.Namespace) -> None:
    """Search FOFA — hash-based cache, F-point guard, summary-only output."""
    t0 = _time.monotonic()
    key = _get_key()
    _validate_key(key)

    info = _resolve_info(key, audit_command="info-lookup")
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
            fpoints_estimated=0,
            tag=cached.get("tag", "") or args.tag,
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
            # The covering cache may start at a non-zero global offset (e.g. page=2).
            # Compute the local offset inside that cached block so we slice the
            # correct rows for the requested page/size.
            cached_start = (covering["cached_page"] - 1) * covering["cached_size"]
            requested_start = (args.page - 1) * args.size
            local_offset = max(0, requested_start - cached_start)
            data = fofa_cache.read(
                covering["query_hash"],
                page=1,
                size=args.size,
                offset=local_offset,
            )
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
                fpoints_estimated=0,
                covering_cache=True,
                tag=covering.get("tag", "") or args.tag,
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
                    args.page, args.size, total, results, tag=args.tag)

    preview = results[:PREVIEW_SIZE]
    fpoints_estimate = 0 if args.page <= 1 else (args.page - 1) * args.size  # estimated, not server-confirmed

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
        fpoints_estimated=fpoints_estimate,
        tag=args.tag,
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
    cache_expired = _is_cache_expired(cached)

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
    """Run statistical aggregation on a FOFA query — cached 5 min (free endpoint)."""
    t0 = _time.monotonic()
    key = _get_key()
    _validate_key(key)

    cache_key = "stats:" + hashlib.sha256(f"{args.query}\x00{args.field}".encode()).hexdigest()
    cached = fofa_cache.get_host_cache(cache_key)
    if cached is not None:
        fofa_errors.output(fofa_errors.make_success(**cached, from_cache=True))
        fofa_cache.log_audit("stats", query_raw=args.query,
                             params={"field": args.field, "from_cache": True},
                             result_code=0, duration_ms=int((_time.monotonic() - t0) * 1000))
        return

    resp = fofa_api.stats(key, args.query, args.field)
    code = _error_code_to_int(resp)
    if resp.get("error"):
        fofa_cache.log_audit("stats", query_raw=args.query,
                             params={"field": args.field},
                             result_code=code, duration_ms=int((_time.monotonic() - t0) * 1000))
        fofa_errors.die(resp.get("msg", "Stats query failed"), "API_ERROR")
    fofa_cache.set_host_cache(cache_key, resp)
    fofa_errors.output(fofa_errors.make_success(**resp, from_cache=False))
    fofa_cache.log_audit("stats", query_raw=args.query,
                         params={"field": args.field},
                         result_code=0, duration_ms=int((_time.monotonic() - t0) * 1000))


def cmd_host(args: argparse.Namespace) -> None:
    """Get detailed info about a specific host — cached 5 min (free endpoint)."""
    t0 = _time.monotonic()
    key = _get_key()
    _validate_key(key)

    cache_key = "host:" + hashlib.sha256(f"{args.host}\x00{args.detail}".encode()).hexdigest()
    cached = fofa_cache.get_host_cache(cache_key)
    if cached is not None:
        fofa_errors.output(fofa_errors.make_success(**cached, from_cache=True))
        fofa_cache.log_audit("host", params={"host": args.host, "detail": args.detail, "from_cache": True},
                             result_code=0, duration_ms=int((_time.monotonic() - t0) * 1000))
        return

    resp = fofa_api.host(key, args.host, args.detail)
    code = _error_code_to_int(resp)
    if resp.get("error"):
        fofa_cache.log_audit("host", params={"host": args.host, "detail": args.detail},
                             result_code=code, duration_ms=int((_time.monotonic() - t0) * 1000))
        fofa_errors.die(resp.get("msg", "Host query failed"), "API_ERROR")
    fofa_cache.set_host_cache(cache_key, resp)
    fofa_errors.output(fofa_errors.make_success(**resp, from_cache=False))
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


def cmd_correlate(args: argparse.Namespace) -> None:
    """Cross-query correlation and de-duplication — all local, zero F-point cost.

    Accepts ``--hashes`` (explicit list) OR ``--tag`` (all queries in one
    assessment target). ``--tag`` is the resilient path: it survives context
    compression, which would otherwise wipe the AI's in-memory hash list and
    force an F-point re-fetch.
    """
    t0 = _time.monotonic()
    hashes = _resolve_hashes(args)
    if not args.tag and len(hashes) < 2:
        fofa_errors.die("correlate requires at least 2 hashes (or use --tag)", "INVALID_PARAM")
    if args.tag and len(hashes) < 2:
        fofa_errors.die(f"tag '{args.tag}' has only {len(hashes)} cached query; need >= 2 to correlate",
                        "INVALID_PARAM")
    try:
        result = fofa_cache.correlate(hashes, key=args.key)
    except ValueError as e:
        fofa_errors.die(str(e), "INVALID_PARAM")
    fofa_errors.output(fofa_errors.make_success(**result))
    fofa_cache.log_audit("correlate", params={"hashes": hashes, "tag": args.tag, "key": args.key},
                         result_code=0, duration_ms=int((_time.monotonic() - t0) * 1000))


def cmd_report(args: argparse.Namespace) -> None:
    """Generate aggregated summary report across cached queries — all local, zero F-point cost.

    Accepts ``--hashes`` OR ``--tag`` (see cmd_correlate). High-risk ports and
    admin-panel keywords default to a broad exposure-assessment list and can be
    overridden via ``--high-risk-ports`` / ``--admin-keywords``.
    """
    t0 = _time.monotonic()
    hashes = _resolve_hashes(args)
    if not hashes:
        fofa_errors.die("report requires at least 1 hash (or use --tag)", "INVALID_PARAM")
    hr_ports = _parse_int_list(args.high_risk_ports, "high-risk-ports") if args.high_risk_ports else None
    admin_kw = tuple(k.strip() for k in args.admin_keywords.split(",") if k.strip()) if args.admin_keywords else None
    if args.limit < 1:
        fofa_errors.die(f"--limit must be >= 1, got {args.limit}", "INVALID_PARAM")
    result = fofa_cache.report(hashes, high_risk_ports=hr_ports, admin_keywords=admin_kw,
                               detail_limit=args.limit)
    fofa_errors.output(fofa_errors.make_success(**result))
    fofa_cache.log_audit("report",
                         params={"hashes": hashes, "tag": args.tag,
                                 "high_risk_ports": list(hr_ports) if hr_ports else None,
                                 "admin_keywords": list(admin_kw) if admin_kw else None},
                         result_code=0, duration_ms=int((_time.monotonic() - t0) * 1000))


def cmd_cache_list(args: argparse.Namespace) -> None:
    """List cached queries — the AI's hash-recovery primitive.

    Long assessment workflows compress out of context; this re-surfaces the
    query_hash ↔ query_raw ↔ tag mapping so ``correlate``/``report`` never
    need a re-fetch. Filter by ``--query`` (substring of query_raw) or
    ``--tag`` (exact target).
    """
    t0 = _time.monotonic()
    queries = fofa_cache.list_queries(query=args.query, tag=args.tag, limit=args.limit)
    fofa_errors.output(fofa_errors.make_success(
        total=len(queries),
        queries=queries,
    ))


def cmd_cache_tag(args: argparse.Namespace) -> None:
    """Retroactively tag (or re-tag) an already-cached query — no re-fetch.

    Assessments often start untagged. This lets the AI group prior searches
    into a target after the fact, so ``correlate --tag`` / ``report --tag``
    still work without re-spending F-points. Pass an empty ``--tag ""`` to clear.
    """
    t0 = _time.monotonic()
    updated = fofa_cache.set_tag(args.hash, args.tag)
    if not updated:
        fofa_errors.die(f"no cached query with hash '{args.hash}'", "NOT_FOUND")
    fofa_errors.output(fofa_errors.make_success(
        tagged=True,
        query_hash=args.hash,
        tag=args.tag,
    ))
    fofa_cache.log_audit("cache-tag", query_hash=args.hash,
                         params={"tag": args.tag},
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


def cmd_audit_clean(args: argparse.Namespace) -> None:
    """Purge audit log entries older than N days."""
    t0 = _time.monotonic()
    cutoff = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d %H:%M:%S")
    deleted = fofa_cache.clean_audit_log(cutoff)
    fofa_errors.output(fofa_errors.make_success(
        deleted=deleted,
        cutoff=cutoff,
    ))
    fofa_cache.log_audit("audit-clean",
                         params={"days": args.days, "cutoff": cutoff, "deleted": deleted},
                         result_code=0, duration_ms=int((_time.monotonic() - t0) * 1000))




# ------------------------------------------------------------------ CLI


def build_parser() -> argparse.ArgumentParser:
    """Construct the argument parser."""
    parser = argparse.ArgumentParser(
        description="FOFA Smart Query — AI-callable search with caching and F-point guard",
    )
    parser.add_argument("--version", action="version", version=f"fofa-skills {fofa_errors.VERSION}")
    # 注意：dest 必须避开子命令参数名（如 audit-log 的 --command/-c），
    # 否则 argparse 会用子命令参数值覆盖子命令名，导致 args.command 永远为 None。
    # 这是 argparse 的已知陷阱——subparser 的参数 dest 与 add_subparsers 的 dest 共享命名空间。
    sub = parser.add_subparsers(dest="_subcommand")

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
    p.add_argument("--tag", default="", help="Tag this query with a target/label (e.g. acme.com) for later --tag grouping in correlate/report")

    # cache-read
    p = sub.add_parser("cache-read", help="Read cached results (paginate/filter)")
    p.add_argument("--hash", required=True, help="Query hash from search result's query_hash")
    p.add_argument("--filter", default="", help="Filter: field=value (exact), field~value (fuzzy), comma-separated")
    p.add_argument("--page", "-p", type=int, default=1, help="Page number")
    p.add_argument("--size", "-s", type=int, default=100, help="Page size")

    # cache-delete
    p = sub.add_parser("cache-delete", help="Delete a cached query by hash")
    p.add_argument("--hash", required=True, help="Query hash to delete")

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

    # cache-list — hash recovery for correlate/report after context compression
    p = sub.add_parser("cache-list", help="List cached queries (recover hashes for correlate/report)")
    p.add_argument("--query", default=None, help="Substring of query_raw to filter (e.g. target domain)")
    p.add_argument("--tag", default=None, help="Exact tag to filter (e.g. acme.com assessment target)")
    p.add_argument("--limit", "-n", type=int, default=100, help="Max entries to return (default 100)")

    # cache-tag — retroactively tag an already-cached query (group untagged searches)
    p = sub.add_parser("cache-tag", help="Tag (or re-tag) an already-cached query — no re-fetch")
    p.add_argument("--hash", required=True, help="Query hash to tag")
    p.add_argument("--tag", required=True, help="Target/label to assign (use empty string to clear)")

    # correlate
    p = sub.add_parser("correlate", help="Cross-query correlation & de-duplication (local, free)")
    p.add_argument("--hashes", default="", help="Comma-separated query hashes to correlate (min 2)")
    p.add_argument("--tag", default="", help="Correlate ALL queries tagged with this target (alternative to --hashes)")
    p.add_argument("--key", default="ip", help="De-duplication key field (default: ip)")

    # report
    p = sub.add_parser("report", help="Generate aggregated summary report (local, free)")
    p.add_argument("--hashes", default="", help="Comma-separated query hashes to include in report")
    p.add_argument("--tag", default="", help="Report on ALL queries tagged with this target (alternative to --hashes)")
    p.add_argument("--high-risk-ports", default=None,
                   help="Override high-risk port list, comma-separated ints (e.g. 22,23,3389)")
    p.add_argument("--admin-keywords", default=None,
                   help="Override admin-panel title keywords, comma-separated (e.g. admin,login,管理)")
    p.add_argument("--limit", "-n", type=int, default=100,
                   help="Cap on high_risk_ports / admin_panels rows (default 100; lower in context-constrained situations)")

    # audit-log
    p = sub.add_parser("audit-log", help="Show recent audit log entries")
    p.add_argument("--limit", "-n", type=int, default=50, help="Max entries to return (default 50)")
    p.add_argument("--command", "-c", default=None, help="Filter by command name (e.g. search, info)")

    # audit-clean
    p = sub.add_parser("audit-clean", help="Purge audit log entries older than N days")
    p.add_argument("--days", "-d", type=int, default=30, help="Keep last N days (default 30)")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if getattr(args, "_subcommand", None) is None:
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
        "cache-clean": cmd_cache_clean,
        "cache-stats": cmd_cache_stats,
        "cache-list": cmd_cache_list,
        "cache-tag": cmd_cache_tag,
        "correlate": cmd_correlate,
        "report": cmd_report,
        "audit-log": cmd_audit_log,
        "audit-clean": cmd_audit_clean,
    }
    try:
        commands[args._subcommand](args)
    except SystemExit:
        raise  # die() uses sys.exit — let it through
    except Exception as e:
        # Never let a traceback corrupt stdout — JSON-only contract.
        fofa_errors.die(f"Internal error: {e}", "INTERNAL_ERROR")


if __name__ == "__main__":
    main()
