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
    tag         TEXT               optional target/label grouping queries in one assessment
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
import re
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

# Default high-risk exposed ports for report(). Covers remote access, DBs,
# caches/search, devops, and unauthenticated admin surfaces commonly seen in
# real exposure assessments. Overridable via report(high_risk_ports=...).
DEFAULT_HIGH_RISK_PORTS = (
    22,    # SSH
    23,    # Telnet
    3389,  # RDP
    5900,  # VNC
    3306,  # MySQL
    5432,  # PostgreSQL
    1433,  # MSSQL
    1521,  # Oracle
    6379,  # Redis
    27017, # MongoDB
    9200,  # Elasticsearch
    11211, # Memcached
    445,   # SMB
    2375,  # Docker daemon (unauth)
    5601,  # Kibana
    6443,  # Kubernetes API
)

# Default admin-panel title keywords for report(). Broad recall over Chinese +
# English panel/product names. Overridable via report(admin_keywords=...).
DEFAULT_ADMIN_KEYWORDS = (
    "管理", "后台", "登录", "管理员",
    "admin", "login", "manage", "management", "dashboard", "console",
    "phpmyadmin", "adminer",
    "grafana", "jenkins", "nacos", "apollo", "consul",
    "jboss", "weblogic", "tomcat", "wildfly",
    "struts", "spring",
)

# 过滤字段名白名单正则：只允许字母开头、字母数字下划线点
# 防止 SQL 注入——field 名直接拼入 SQL，必须严格校验
_FIELD_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


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
                tag        TEXT NOT NULL DEFAULT '',
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

            CREATE TABLE IF NOT EXISTS host_cache (
                key        TEXT PRIMARY KEY,
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
        # tag column on query_cache (target grouping for assessment workflows)
        _add_column_if_not_exists(conn, "query_cache", "tag", "TEXT", "")

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
            "SELECT query_hash, page AS cached_page, size AS cached_size, total, tag "
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
    tag: str = "",
    db_path: Optional[str] = None,
) -> None:
    """Persist query metadata and results to cache.

    *tag* is an optional target/label that groups queries belonging to one
    assessment (e.g. "acme.com"). It lets ``correlate``/``report`` operate
    on a whole target without the AI having to remember individual hashes.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ttl = FULL_TRUE_TTL_HOURS if full else FULL_FALSE_TTL_HOURS
    expires = (datetime.now() + timedelta(hours=ttl)).strftime("%Y-%m-%d %H:%M:%S")

    with _get_db(db_path) as conn:
        # Preserve an existing tag if this save omits one (covering-cache refresh).
        if not tag:
            existing = conn.execute(
                "SELECT tag FROM query_cache WHERE query_hash = ?", (query_hash,)
            ).fetchone()
            if existing is not None:
                tag = existing["tag"] or ""
        conn.execute(
            """INSERT OR REPLACE INTO query_cache
               (query_hash, query_raw, fields, full, page, size, total, tag, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (query_hash, query_raw, fields, int(full), page, size, total, tag, now, expires),
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
    offset: Optional[int] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Read cached results with optional filtering and pagination.

    Args:
        cache_id: query_hash to read from.
        filters: list of {"field": str, "op": "eq"|"like", "value": str} dicts.
        page: 1-based page number. Used to compute offset when *offset* is None.
        size: results per page.
        offset: explicit 0-based offset into the cached rows. If None, computed
            as (page - 1) * size. Useful when slicing out of a covering cache
            whose first stored row does not correspond to global offset 0.
        db_path: optional database path.

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
                # 白名单校验 field 名，防止 SQL 注入
                if not _FIELD_NAME_RE.fullmatch(field):
                    raise ValueError(f"Invalid filter field name: {field!r}")
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

        if offset is None:
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


# Cache TTL for host/stats responses (both free endpoints).
HOST_CACHE_TTL: int = 300  # 5 minutes


def get_host_cache(cache_key: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Return cached host/stats response if within TTL, else None."""
    with _get_db(db_path) as conn:
        row = conn.execute(
            "SELECT data, updated_at FROM host_cache WHERE key = ?", (cache_key,)
        ).fetchone()
    if row is None:
        return None
    if time.time() - row["updated_at"] > HOST_CACHE_TTL:
        return None
    return json.loads(row["data"])


def set_host_cache(cache_key: str, data: Dict[str, Any], db_path: Optional[str] = None) -> None:
    """Store host/stats response with current timestamp."""
    with _get_db(db_path) as conn:
        conn.execute(
            "INSERT OR REPLACE INTO host_cache (key, data, updated_at) VALUES (?, ?, ?)",
            (cache_key, json.dumps(data, ensure_ascii=False), time.time()),
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


def list_queries(
    query: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 100,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """List cached queries with optional filters — the AI's "hash recovery" primitive.

    Long assessment workflows compress out of context; this lets the AI recover
    the query_hash ↔ query_raw ↔ tag mapping it lost, so ``correlate``/``report``
    never need a re-fetch (re-spend of F-points).

    Args:
        query: substring / regex matched against query_raw (case-insensitive).
               Use to find "everything I queried about acme.com".
        tag:    exact tag match (e.g. "acme.com" target grouping).
        limit:  cap on rows returned (default 100).

    Returns list of {query_hash, query_raw, fields, full, page, size, total,
    tag, created_at, expires_at, result_count} ordered newest-first.
    """
    clauses: List[str] = []
    params: List[Any] = []
    if query:
        # LIKE with escaped wildcards so a literal %/_ in the query is matched as-is
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append("query_raw LIKE ? ESCAPE '\\'")
        params.append(f"%{escaped}%")
    if tag:
        clauses.append("tag = ?")
        params.append(tag)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(limit)

    with _get_db(db_path) as conn:
        rows = conn.execute(
            f"""SELECT qc.query_hash, qc.query_raw, qc.fields, qc.full, qc.page,
                       qc.size, qc.total, qc.tag, qc.created_at, qc.expires_at,
                       (SELECT COUNT(*) FROM query_result qr WHERE qr.cache_id = qc.query_hash) AS result_count
                FROM query_cache qc{where}
                ORDER BY qc.created_at DESC LIMIT ?""",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def resolve_tag_to_hashes(
    tag: str,
    db_path: Optional[str] = None,
) -> List[str]:
    """Return all query_hash values tagged with *tag*, newest-first.

    Used by ``correlate --tag`` and ``report --tag`` so the AI can operate on
    a whole assessment target without enumerating hashes.
    """
    with _get_db(db_path) as conn:
        rows = conn.execute(
            "SELECT query_hash FROM query_cache WHERE tag = ? "
            "ORDER BY created_at DESC",
            (tag,),
        ).fetchall()
    return [r["query_hash"] for r in rows]


def set_tag(
    query_hash: str,
    tag: str,
    db_path: Optional[str] = None,
) -> int:
    """Retroactively tag an already-cached query. Returns rows updated (0 or 1).

    Lets the AI group searches that were performed without ``--tag`` into an
    assessment target — no re-fetch, no F-point re-spend. Empty *tag* clears
    an existing tag.
    """
    with _get_db(db_path) as conn:
        cur = conn.execute(
            "UPDATE query_cache SET tag = ? WHERE query_hash = ?",
            (tag, query_hash),
        )
        conn.commit()
        return cur.rowcount


# ------------------------------------------------------------------ correlate / report


def correlate(
    hashes: List[str],
    key: str = "ip",
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Cross-query correlation and de-duplication.

    Merges results from multiple cached queries, de-duplicating by *key*
    (default ``ip``). Returns counts and per-query unique assets without
    loading all rows into memory — all work happens in SQLite.

    Returns:
        {
            "total_unique": int,          # unique key values across all queries
            "duplicates_removed": int,    # total rows minus unique keys
            "per_query": [{query_hash, query_raw, total, unique_by_key}],
            "key": str,
            "overlap_matrix": [[...]],    # NxN; diagonal = per-query unique count, off-diagonal = shared
        }
    """
    # Validate key field
    if not _FIELD_NAME_RE.fullmatch(key):
        raise ValueError(f"Invalid correlation key: {key!r}")

    col = key if key in INDEXED_FIELDS else f"json_extract(data, '$.{key}')"

    with _get_db(db_path) as conn:
        # Gather metadata for each hash
        metas: List[Dict[str, Any]] = []
        for h in hashes:
            row = conn.execute(
                "SELECT query_hash, query_raw, total FROM query_cache WHERE query_hash = ?",
                (h,),
            ).fetchone()
            if row:
                metas.append(dict(row))
            else:
                metas.append({"query_hash": h, "query_raw": None, "total": 0})

        # Global unique key values via UNION
        union_parts = []
        union_params: List[str] = []
        for h in hashes:
            union_parts.append(f"SELECT {col} AS k FROM query_result WHERE cache_id = ? AND {col} != ''")
            union_params.append(h)
        union_sql = " UNION ".join(union_parts)
        unique_rows = conn.execute(union_sql, union_params).fetchall()
        total_unique = len(unique_rows)

        # Total non-empty-key rows across all queries (empty keys are not
        # real assets and must not inflate the duplicates count).
        placeholders = ",".join("?" * len(hashes))
        total_rows_row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM query_result WHERE cache_id IN ({placeholders}) AND {col} != ''",
            hashes,
        ).fetchone()
        total_rows: int = total_rows_row["cnt"]

        # Per-query unique counts (also seeds the overlap-matrix diagonal)
        n = len(hashes)
        overlap_matrix: List[List[int]] = [[0] * n for _ in range(n)]
        per_query: List[Dict[str, Any]] = []
        for i, h in enumerate(hashes):
            unique_count_row = conn.execute(
                f"SELECT COUNT(DISTINCT {col}) AS cnt FROM query_result WHERE cache_id = ? AND {col} != ''",
                (h,),
            ).fetchone()
            unique_cnt = unique_count_row["cnt"]
            overlap_matrix[i][i] = unique_cnt  # diagonal = set cardinality
            per_query.append({
                "query_hash": h,
                "query_raw": metas[i].get("query_raw"),
                "total": metas[i].get("total", 0),
                "unique_by_key": unique_cnt,
            })

        # Overlap matrix off-diagonal: for each pair (i, j), shared key values
        for i in range(n):
            for j in range(i + 1, n):
                shared_row = conn.execute(
                    f"""SELECT COUNT(*) AS cnt FROM (
                        SELECT DISTINCT {col} AS k FROM query_result WHERE cache_id = ? AND {col} != ''
                        INTERSECT
                        SELECT DISTINCT {col} AS k FROM query_result WHERE cache_id = ? AND {col} != ''
                    )""", (hashes[i], hashes[j])).fetchone()
                shared = shared_row["cnt"]
                overlap_matrix[i][j] = shared
                overlap_matrix[j][i] = shared

    return {
        "total_unique": total_unique,
        "duplicates_removed": max(0, total_rows - total_unique),
        "per_query": per_query,
        "key": key,
        "overlap_matrix": overlap_matrix,
    }


def report(
    hashes: List[str],
    db_path: Optional[str] = None,
    high_risk_ports: Optional[tuple] = None,
    admin_keywords: Optional[tuple] = None,
    detail_limit: int = 100,
) -> Dict[str, Any]:
    """Generate a summary report across multiple cached queries.

    Aggregates port, country, server, protocol distributions and high-risk
    indicators directly in SQLite — no API calls, no context flooding.

    Args:
        high_risk_ports: override the default high-risk port list (ints).
        admin_keywords: override the default admin-panel title keywords (strs).
        detail_limit: cap on ``high_risk_ports`` and ``admin_panels`` rows
            (default 100). Lower this in context-constrained situations.

    Returns:
        {
            "total_assets": int,
            "total_unique_ips": int,
            "by_port": [{"port": int, "count": int}],
            "by_country": [{"country": str, "count": int}],
            "by_protocol": [{"protocol": str, "count": int}],
            "by_server": [{"server": str, "count": int}],
            "high_risk_ports": [{"ip": str, "port": int, "host": str}],
            "admin_panels": [{"ip": str, "host": str, "title": str}],
            "per_query": [{hash, query_raw, total}],
        }
    """
    if not hashes:
        return {
            "total_assets": 0,
            "total_unique_ips": 0,
            "by_port": [],
            "by_country": [],
            "by_protocol": [],
            "by_server": [],
            "high_risk_ports": [],
            "admin_panels": [],
            "per_query": [],
        }

    placeholders = ",".join("?" * len(hashes))
    high_risk_ports = tuple(high_risk_ports) if high_risk_ports else DEFAULT_HIGH_RISK_PORTS
    # Normalize ports to int (CLI passes strings) and dedupe, preserving order.
    normalized_ports: List[int] = []
    seen_ports: set = set()
    for p in high_risk_ports:
        try:
            pi = int(p)
        except (ValueError, TypeError):
            continue
        if pi not in seen_ports:
            seen_ports.add(pi)
            normalized_ports.append(pi)
    high_risk_ports = tuple(normalized_ports) or DEFAULT_HIGH_RISK_PORTS
    hr_placeholders = ",".join("?" * len(high_risk_ports))
    admin_keywords = tuple(admin_keywords) if admin_keywords else DEFAULT_ADMIN_KEYWORDS

    with _get_db(db_path) as conn:
        total_row = conn.execute(
            f"SELECT COUNT(*) AS cnt FROM query_result WHERE cache_id IN ({placeholders})",
            hashes,
        ).fetchone()
        total_assets: int = total_row["cnt"]

        unique_ip_row = conn.execute(
            f"SELECT COUNT(DISTINCT ip) AS cnt FROM query_result WHERE cache_id IN ({placeholders}) AND ip != ''",
            hashes,
        ).fetchone()
        total_unique_ips: int = unique_ip_row["cnt"]

        # Distribution queries (top 20 each)
        def _agg(col: str, label: str, limit: int = 20) -> List[Dict[str, Any]]:
            rows = conn.execute(
                f"SELECT {col} AS {label}, COUNT(*) AS cnt FROM query_result "
                f"WHERE cache_id IN ({placeholders}) AND {col} != '' "
                f"GROUP BY {col} ORDER BY cnt DESC LIMIT ?",
                (*hashes, limit),
            ).fetchall()
            return [dict(r) for r in rows]

        by_port = _agg("port", "port")
        by_country = _agg("country", "country")
        by_protocol = _agg("protocol", "protocol")
        by_server = _agg("server", "server")

        # High-risk exposed ports
        hr_rows = conn.execute(
            f"""SELECT DISTINCT ip, port, host FROM query_result
                WHERE cache_id IN ({placeholders}) AND port IN ({hr_placeholders}) AND ip != ''
                ORDER BY ip LIMIT ?""",
            (*hashes, *high_risk_ports, detail_limit),
        ).fetchall()
        high_risk_list = [dict(r) for r in hr_rows]

        # Admin panels (title LIKE any keyword)
        admin_clauses = " OR ".join(["title LIKE ?" for _ in admin_keywords])
        admin_params = [f"%{kw}%" for kw in admin_keywords]
        admin_rows = conn.execute(
            f"""SELECT DISTINCT ip, host, title FROM query_result
                WHERE cache_id IN ({placeholders}) AND ({admin_clauses})
                ORDER BY ip LIMIT ?""",
            (*hashes, *admin_params, detail_limit),
        ).fetchall()
        admin_list = [dict(r) for r in admin_rows]

        # Per-query metadata (include a placeholder for missing hashes so the
        # caller can tell which hash was not found — mirrors correlate()).
        per_query: List[Dict[str, Any]] = []
        for h in hashes:
            row = conn.execute(
                "SELECT query_hash, query_raw, total FROM query_cache WHERE query_hash = ?",
                (h,),
            ).fetchone()
            if row:
                per_query.append(dict(row))
            else:
                per_query.append({"query_hash": h, "query_raw": None, "total": 0})

    return {
        "total_assets": total_assets,
        "total_unique_ips": total_unique_ips,
        "by_port": by_port,
        "by_country": by_country,
        "by_protocol": by_protocol,
        "by_server": by_server,
        "high_risk_ports": high_risk_list,
        "admin_panels": admin_list,
        "per_query": per_query,
    }


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


def clean_audit_log(before_date: str, db_path: Optional[str] = None) -> int:
    """Delete audit log entries older than *before_date* (ISO format). Returns deleted count."""
    with _get_db(db_path) as conn:
        cur = conn.execute("DELETE FROM audit_log WHERE timestamp < ?", (before_date,))
        conn.commit()
    return cur.rowcount


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
