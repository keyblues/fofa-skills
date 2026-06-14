"""SQLite cache layer for FOFA query results.

Stores query metadata and results in a local SQLite database.
All filtering uses parameterized queries to prevent SQL injection.
Uses only Python stdlib (sqlite3, json, hashlib, datetime).

Database schema
----------------
query_cache — one row per unique query (hash → metadata)
    query_hash  TEXT PRIMARY KEY   SHA-256 of (query|fields|full|page|size)
    query_raw   TEXT               original FOFA query string
    fields      TEXT               comma-separated field list
    full        INTEGER            1 = full history, 0 = recent year
    page        INTEGER            requested page number
    size        INTEGER            requested page size
    total       INTEGER            total results returned
    created_at  TEXT               ISO datetime
    expires_at  TEXT               ISO datetime (24h for full=0, 7d for full=1)

query_result — one row per result item
    id          INTEGER PK AUTO    row id
    cache_id    TEXT FK → query_cache
    data        TEXT               full JSON of the result row
    ip, port, protocol, host, domain, title, server,
    country, banner, jarm, icp, cname — extracted index columns

info_cache — single-row account info cache (TTL 5 min)
    id          INTEGER PK (1)
    data        TEXT               JSON of account info response
    updated_at  REAL               unix timestamp

audit_log — operation audit trail
    id          INTEGER PK AUTO
    timestamp   TEXT               ISO datetime
    command     TEXT               subcommand name
    query_hash  TEXT               associated cache hash (nullable)
    query_raw   TEXT               original query string (nullable)
    params      TEXT               JSON of additional parameters (nullable)
    result_code INTEGER            0=success, else error code
    duration_ms INTEGER            execution time in milliseconds
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

DB_PATH = os.environ.get(
    "FOFA_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", "fofa_cache.db"),
)

INFO_CACHE_TTL = 300  # seconds
FULL_FALSE_TTL_HOURS = 24
FULL_TRUE_TTL_HOURS = 168  # 7 days

INDEXED_FIELDS = frozenset({
    "ip", "port", "protocol", "host", "domain", "title", "server",
    "country", "banner", "jarm", "icp", "cname",
})


@contextmanager
def _get_db(db_path: Optional[str] = None):
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def _add_column_if_not_exists(conn: sqlite3.Connection, table: str, column: str,
                              col_type: str, default: str = "") -> None:
    """Safely add a column to an existing table (migration helper)."""
    try:
        columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type} DEFAULT '{default}'")
    except sqlite3.OperationalError:
        pass


def init_db(db_path: Optional[str] = None) -> None:
    """Create tables and indexes if they don't exist."""
    with _get_db(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS query_cache (
                query_hash TEXT PRIMARY KEY,
                query_raw  TEXT NOT NULL,
                fields     TEXT NOT NULL,
                full       INTEGER NOT NULL DEFAULT 0,
                page       INTEGER NOT NULL DEFAULT 1,
                size       INTEGER NOT NULL DEFAULT 100,
                total      INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                expires_at TEXT
            );

            CREATE TABLE IF NOT EXISTS query_result (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                cache_id TEXT NOT NULL,
                data     TEXT NOT NULL,
                ip       TEXT DEFAULT '',
                port     INTEGER DEFAULT 0,
                protocol TEXT DEFAULT '',
                host     TEXT DEFAULT '',
                domain   TEXT DEFAULT '',
                title    TEXT DEFAULT '',
                server   TEXT DEFAULT '',
                country  TEXT DEFAULT '',
                banner   TEXT DEFAULT '',
                jarm     TEXT DEFAULT '',
                icp      TEXT DEFAULT '',
                cname    TEXT DEFAULT '',
                FOREIGN KEY (cache_id) REFERENCES query_cache(query_hash)
            );

            CREATE INDEX IF NOT EXISTS idx_result_cache_id ON query_result(cache_id);
            CREATE INDEX IF NOT EXISTS idx_result_ip ON query_result(ip);
            CREATE INDEX IF NOT EXISTS idx_result_port ON query_result(port);
            CREATE INDEX IF NOT EXISTS idx_result_host ON query_result(host);
            CREATE INDEX IF NOT EXISTS idx_result_banner ON query_result(banner);
            CREATE INDEX IF NOT EXISTS idx_result_jarm ON query_result(jarm);
            CREATE INDEX IF NOT EXISTS idx_result_icp ON query_result(icp);

            CREATE TABLE IF NOT EXISTS info_cache (
                id         INTEGER PRIMARY KEY CHECK (id = 1),
                data       TEXT NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT NOT NULL,
                command     TEXT NOT NULL,
                query_hash  TEXT,
                query_raw   TEXT,
                params      TEXT,
                result_code INTEGER NOT NULL DEFAULT 0,
                duration_ms INTEGER NOT NULL DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
            CREATE INDEX IF NOT EXISTS idx_audit_command ON audit_log(command);
        """)

        # Migrate existing tables: add new columns if they don't exist
        for col, ctype, default in [
            ("banner", "TEXT", ""),
            ("jarm", "TEXT", ""),
            ("icp", "TEXT", ""),
            ("cname", "TEXT", ""),
        ]:
            _add_column_if_not_exists(conn, "query_result", col, ctype, default)

        conn.commit()


def hash_query(query_raw: str, fields: str, full: bool, page: int, size: int) -> str:
    """Produce a deterministic SHA-256 hash for cache lookup."""
    raw = f"{query_raw}|{fields}|{int(full)}|{page}|{size}"
    return hashlib.sha256(raw.encode()).hexdigest()


def lookup(query_hash: str, db_path: Optional[str] = None, *, allow_expired: bool = False) -> Optional[Dict[str, Any]]:
    """Return cached query metadata or None.

    By default, expired entries are treated as cache misses (return None).
    Set allow_expired=True to retrieve metadata even if the TTL has passed.
    """
    with _get_db(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM query_cache WHERE query_hash = ?", (query_hash,)
        ).fetchone()
    if row is None:
        return None
    result = dict(row)
    if not allow_expired and result.get("expires_at"):
        try:
            expires = datetime.strptime(result["expires_at"], "%Y-%m-%d %H:%M:%S")
            if datetime.now() > expires:
                return None
        except (ValueError, TypeError):
            pass  # malformed expires_at → treat as fresh
    return result


def find_covering_cache(
    query_raw: str,
    fields: str,
    full: bool,
    page: int,
    size: int,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Find a page-1 cache entry that covers the requested page range.

    When a user requests page N, but we already have a cached result for the
    same query with page=1 whose stored data covers rows up to N*size, we can
    serve the request from cache without a new API call.

    Returns the cache metadata dict (with query_hash) if found, else None.
    """
    with _get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT query_hash, page AS cached_page, size AS cached_size, total "
            "FROM query_cache WHERE query_raw = ? AND fields = ? AND full = ? "
            "AND (expires_at IS NULL OR expires_at > ?)",
            (query_raw, fields, int(full), datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ).fetchall()

    requested_end = page * size

    for row in rows:
        cached_page = row["cached_page"]
        cached_size = row["cached_size"]
        total = row["total"]
        # How many results are actually stored for this cache entry
        actual_stored = min(cached_size, max(0, total - (cached_page - 1) * cached_size))
        # The global offset range this cache covers
        cached_start = (cached_page - 1) * cached_size
        cached_end = cached_start + actual_stored

        if cached_start <= (page - 1) * size and cached_end >= requested_end:
            return dict(row)

    return None


def save(
    query_hash: str,
    query_raw: str,
    fields: str,
    full: bool,
    page: int,
    size: int,
    total: int,
    results: List[Dict[str, Any]],
    db_path: Optional[str] = None,
) -> None:
    """Persist query metadata and results to cache."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ttl = FULL_TRUE_TTL_HOURS if full else FULL_FALSE_TTL_HOURS
    expires = (datetime.now() + timedelta(hours=ttl)).strftime("%Y-%m-%d %H:%M:%S")

    with _get_db(db_path) as conn:
        conn.execute(
            """INSERT OR REPLACE INTO query_cache
               (query_hash, query_raw, fields, full, page, size, total, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (query_hash, query_raw, fields, int(full), page, size, total, now, expires),
        )
        conn.execute("DELETE FROM query_result WHERE cache_id = ?", (query_hash,))
        for item in results:
            data_json = json.dumps(item, ensure_ascii=False)

            try:
                port_val = int(item.get("port", 0) or 0)
            except (ValueError, TypeError):
                port_val = 0

            conn.execute(
                """INSERT INTO query_result
                   (cache_id, data, ip, port, protocol, host, domain, title, server,
                    country, banner, jarm, icp, cname)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    query_hash, data_json,
                    str(item.get("ip", "") or ""),
                    port_val,
                    str(item.get("protocol", "") or ""),
                    str(item.get("host", "") or ""),
                    str(item.get("domain", "") or ""),
                    str(item.get("title", "") or ""),
                    str(item.get("server", "") or ""),
                    str(item.get("country", "") or ""),
                    str(item.get("banner", "") or ""),
                    str(item.get("jarm", "") or ""),
                    str(item.get("icp", "") or ""),
                    str(item.get("cname", "") or ""),
                ),
            )
        conn.commit()


def read(
    cache_id: str,
    filters: Optional[List[Dict[str, str]]] = None,
    page: int = 1,
    size: int = 100,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Read cached results with optional filtering and pagination.

    Args:
        cache_id: query_hash to read from.
        filters: list of {"field": str, "op": "eq"|"like", "value": str} dicts.
        page: 1-based page number.
        size: results per page.

    Returns:
        {"total": int, "page": int, "size": int, "results": [...]}
    """
    with _get_db(db_path) as conn:
        where: List[str] = ["cache_id = ?"]
        params: List[Any] = [cache_id]

        if filters:
            for f in filters:
                field = f["field"]
                op = f.get("op", "eq")
                value = f["value"]
                col = field if field in INDEXED_FIELDS else f"json_extract(data, '$.{field}')"
                if op == "eq":
                    where.append(f"{col} = ?")
                    params.append(value)
                elif op == "like":
                    where.append(f"{col} LIKE ?")
                    params.append(f"%{value}%")

        where_clause = " AND ".join(where)

        count_row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM query_result WHERE {where_clause}", params
        ).fetchone()
        total: int = count_row["cnt"]

        offset = (page - 1) * size
        rows = conn.execute(
            f"SELECT data FROM query_result WHERE {where_clause} ORDER BY id LIMIT ? OFFSET ?",
            params + [size, offset],
        ).fetchall()

    return {
        "total": total,
        "page": page,
        "size": size,
        "results": [json.loads(r["data"]) for r in rows],
    }


def clean(before_date: str, db_path: Optional[str] = None) -> int:
    """Delete cache entries older than *before_date* (ISO format). Returns deleted row count."""
    with _get_db(db_path) as conn:
        cur1 = conn.execute(
            "DELETE FROM query_result WHERE cache_id IN "
            "(SELECT query_hash FROM query_cache WHERE created_at < ?)",
            (before_date,),
        )
        cur2 = conn.execute("DELETE FROM query_cache WHERE created_at < ?", (before_date,))
        conn.commit()
    return cur1.rowcount + cur2.rowcount


def get_info_cache(db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Return cached account info if within TTL, else None."""
    with _get_db(db_path) as conn:
        row = conn.execute(
            "SELECT data, updated_at FROM info_cache WHERE id = 1"
        ).fetchone()
    if row is None:
        return None
    if time.time() - row["updated_at"] > INFO_CACHE_TTL:
        return None
    return json.loads(row["data"])


def set_info_cache(data: Dict[str, Any], db_path: Optional[str] = None) -> None:
    """Store account info with current timestamp."""
    with _get_db(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO info_cache (id, data, updated_at) VALUES (1, ?, ?)",
            (json.dumps(data, ensure_ascii=False), time.time()),
        )
        conn.commit()


def cache_stats(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Return count of cached queries and result rows."""
    with _get_db(db_path) as conn:
        queries: int = conn.execute("SELECT COUNT(*) AS cnt FROM query_cache").fetchone()["cnt"]
        results: int = conn.execute("SELECT COUNT(*) AS cnt FROM query_result").fetchone()["cnt"]
        audit: int = conn.execute("SELECT COUNT(*) AS cnt FROM audit_log").fetchone()["cnt"]
    return {"cached_queries": queries, "cached_results": results, "audit_entries": audit}


def delete_cache(query_hash: str, db_path: Optional[str] = None) -> bool:
    """Delete a single cached query and its results. Returns True if deleted."""
    with _get_db(db_path) as conn:
        conn.execute("DELETE FROM query_result WHERE cache_id = ?", (query_hash,))
        cur = conn.execute("DELETE FROM query_cache WHERE query_hash = ?", (query_hash,))
        conn.commit()
        return cur.rowcount > 0


def export_cache(
    query_hash: str,
    fmt: str = "json",
    output_path: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Export cached results to a file. Returns {path, total, format}.

    Args:
        query_hash: cache id to export.
        fmt: "json" or "csv".
        output_path: file path to write. Auto-generated if None.
    """
    # Read in batches to avoid loading the entire dataset into memory at once
    batch_size = 5000
    all_results: List[Dict[str, Any]] = []
    page_num = 1
    while True:
        batch = read(query_hash, page=page_num, size=batch_size, db_path=db_path)
        all_results.extend(batch["results"])
        if len(all_results) >= batch["total"] or not batch["results"]:
            break
        page_num += 1

    if output_path is None:
        ext = "json" if fmt == "json" else "csv"
        output_path = os.path.join(
            os.path.dirname(db_path or DB_PATH), f"export_{query_hash[:12]}.{ext}"
        )

    if fmt == "json":
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(all_results, f, ensure_ascii=False, indent=2)
    elif fmt == "csv":
        import csv
        results = all_results
        if not results:
            with open(output_path, "w", encoding="utf-8", newline="") as f:
                f.write("")
        else:
            headers = list(results[0].keys())
            with open(output_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(results)

    return {"path": os.path.abspath(output_path), "total": len(all_results), "format": fmt}


# ------------------------------------------------------------------ audit log


def log_audit(
    command: str,
    query_hash: Optional[str] = None,
    query_raw: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    result_code: int = 0,
    duration_ms: int = 0,
    db_path: Optional[str] = None,
) -> None:
    """Record an operation in the audit log.

    Args:
        command: subcommand name (e.g. "search", "info", "cache-read").
        query_hash: associated cache hash, if any.
        query_raw: original FOFA query string, if any.
        params: additional parameters as a dict (serialized to JSON).
        result_code: 0 for success, else error code.
        duration_ms: execution time in milliseconds.
    """
    with _get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO audit_log (timestamp, command, query_hash, query_raw, params, result_code, duration_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                command,
                query_hash,
                query_raw,
                json.dumps(params, ensure_ascii=False) if params else None,
                result_code,
                duration_ms,
            ),
        )
        conn.commit()


def read_audit_log(
    limit: int = 50,
    command: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Read recent audit log entries.

    Args:
        limit: maximum entries to return.
        command: filter by command name, if provided.

    Returns:
        List of audit log entry dicts, most recent first.
    """
    with _get_db(db_path) as conn:
        if command:
            rows = conn.execute(
                "SELECT * FROM audit_log WHERE command = ? ORDER BY id DESC LIMIT ?",
                (command, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
    return [dict(row) for row in rows]
