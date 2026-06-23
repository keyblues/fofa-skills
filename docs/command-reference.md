# Command Reference

> Extracted from SKILL.md. Full parameter reference and example outputs for all 14 subcommands: info, search, stats, host, cache-read, cache-delete, cache-clean, cache-stats, cache-list, cache-tag, correlate, report, audit-log, audit-clean.

## Command Reference

### info — Account info (cached 5 min, free)

```
python scripts/fofa_smart.py info
python scripts/fofa_smart.py info --refresh
```

```json
{"__fofa__": true, "error": false, "from_cache": true, "email": "...", "isvip": true, "fcoin": 0, ...}
```

### search — Asset search

```
python scripts/fofa_smart.py search \
  -q 'host=".edu" && port="443"' \
  -f "ip,port,host,title,server" \
  -p 1 -s 100
```

| Param | Required | Description |
|-------|----------|-------------|
| `-q` | Yes | FOFA query string |
| `-f` | No | Return fields (`--fields`), default `ip,port,protocol,host,domain,title,server` |
| `-p` | No | Page number, default 1 |
| `-s` | No | Page size, default 100, max 10000 |
| `--full` | No | Search all historical data |
| `--no-cache` | No | Skip cache, force fresh query |
| `--allow-fpoints` | No | Allow F-point spend (pagination), only with explicit user authorization |
| `--tag` | No | Tag this query with a target/label (e.g. `acme.com`) so later `correlate --tag` / `report --tag` / `cache-list --tag` can group all queries in one assessment without the AI tracking individual hashes |

> **Warning**: `-f` means `--fields` (which columns to return) in `search`, but `--field` (aggregation dimension) in `stats` — different meanings.

Returns summary (not full data):
```json
{
  "__fofa__": true,
  "error": false,
  "from_cache": false,
  "query_hash": "abc123...",
  "query_raw": "host=\".edu\" && port=\"443\"",
  "fields": "ip,port,host,title,server",
  "full": false,
  "page": 1,
  "size": 100,
  "total": 10000,
  "preview": [{"ip": "...", "port": "443", ...}, ...],
  "fpoints_estimated": 0
}
```

When covering cache is used (page>1 served from existing page=1 cache):
```json
{
  "__fofa__": true,
  "error": false,
  "from_cache": true,
  "covering_cache": true,
  "query_hash": "abc123...",
  ...
}
```

### stats — Statistical aggregation (free, cached 5 min)

```
python scripts/fofa_smart.py stats -q 'app="Apache"' -f "port"
python scripts/fofa_smart.py stats -q 'app="Apache"' -f "country,port"
```

| Param | Required | Description |
|-------|----------|-------------|
| `-q` | Yes | FOFA query string |
| `-f` | Yes | Aggregation field(s) (`--field`), e.g. `country`, `port`, `protocol`. Comma-separated for multi-field aggregation |

> **Warning**: This `-f` is `--field` (aggregation dimension), different from `search`'s `-f` (`--fields`, return columns). Supports comma-separated values for multi-field aggregation.

```json
{
  "__fofa__": true,
  "error": false,
  "consumed_fpoint": 0,
  "required_fpoints": 0,
  "size": 1234,
  "distinct": {"ip": 1234, "ipc": 50},
  "aggs": {
    "port": [
      {"count": 500, "name": "80", "detail": {}},
      {"count": 300, "name": "443", "detail": {}}
    ]
  },
  "query": "app=\"Apache\"",
  "lastupdatetime": "2026-06-22"
}
```

> **Note**: FOFA stats API returns `aggs` as a **dict keyed by field name** (not a flat list). Each entry has `name` (the value), `count`, and `detail`. For multi-field aggregation with `country`, the `countries` key contains nested `regions` arrays. The response also includes `consumed_fpoint`, `required_fpoints`, `size` (total), `distinct` (unique counts), and `lastupdatetime`.

### host — Host details (free, cached 5 min)

```
python scripts/fofa_smart.py host --host "1.1.1.1"
python scripts/fofa_smart.py host --host "1.1.1.1" --detail
```

| Param | Required | Description |
|-------|----------|-------------|
| `--host` | Yes | Target IP or domain |
| `--detail` | No | Include per-port protocol/product/service details |

Without `--detail`:
```json
{
  "__fofa__": true,
  "error": false,
  "host": "1.1.1.1",
  "ip": "1.1.1.1",
  "asn": 13335,
  "org": "Cloudflare, Inc.",
  "country_name": "United States",
  "country_code": "US",
  "port": [80, 443],
  "protocol": ["http", "https"],
  "domain": ["example.com"]
}
```

With `--detail`, adds a `details` list containing FOFA's per-port service info:
```json
{
  "__fofa__": true,
  "error": false,
  "host": "1.1.1.1",
  "ip": "1.1.1.1",
  "asn": 13335,
  "org": "Cloudflare, Inc.",
  "country_name": "United States",
  "country_code": "US",
  "port": [80, 443],
  "protocol": ["http", "https"],
  "domain": ["example.com"],
  "details": [
    {
      "error": false,
      "consumed_fpoint": 0,
      "required_fpoints": 0,
      "ports": [
        {"port": 80, "protocol": "http", "update_time": "2026-06-22 00:00:00", "products": [...]},
        {"port": 443, "protocol": "https", "update_time": "2026-06-22 00:00:00", "products": [...]}
      ],
      "update_time": "2026-06-22 00:00:00"
    }
  ]
}
```

> **Note**: The `--detail` response structure is passed through from FOFA API as-is. Each `details` entry contains a `ports` array with per-port `protocol`, `update_time`, and `products` (service fingerprint info). The response also includes `country_code` and `domain` fields not present in the non-detail response.

### cache-read — Read cached results

```
python scripts/fofa_smart.py cache-read \
  --hash "abc123..." --filter "port=443,title~admin" -p 1 -s 50
```

| Param | Description |
|-------|-------------|
| `--hash` | Query hash from `search` result's `query_hash` |
| `--filter` | `field=value` exact match, `field~value` fuzzy match, comma-separated |
| `-p` | Page number |
| `-s` | Page size |

Note: `cache-read` returns expired cache data with `cache_expired: true` — re-run `search` for fresh data.

### cache-delete — Delete a cached query

```
python scripts/fofa_smart.py cache-delete --hash "abc123..."
```

### cache-clean — Purge old cache

```
python scripts/fofa_smart.py cache-clean --days 30
```

### cache-stats — Cache statistics

```
python scripts/fofa_smart.py cache-stats
```

### cache-list — List cached queries (hash recovery)

Lists cached queries with their `query_hash`, `query_raw`, `tag`, and result count. This is the **recovery primitive** for `correlate`/`report`: long assessment workflows compress out of context and wipe the AI's in-memory hash list — `cache-list` re-surfaces the mapping so you never need a re-fetch (re-spend of F-points) to remember what you already searched.

```
# List everything (newest first)
python scripts/fofa_smart.py cache-list

# Find all queries about a target domain (substring of query_raw)
python scripts/fofa_smart.py cache-list --query "acme.com"

# Find all queries tagged for one assessment target
python scripts/fofa_smart.py cache-list --tag acme.com
```

Flags: `--query` (substring of `query_raw`), `--tag` (exact tag), `--limit/-n` (default 100).

### cache-tag — Tag (or re-tag) an already-cached query

Retroactively assigns a target/label to a cached query — no re-fetch, no F-point re-spend. Use when an assessment started without `--tag` and you want to group prior searches so `correlate --tag` / `report --tag` work.

```
# Tag a previously-untagged query
python scripts/fofa_smart.py cache-tag --hash h1 --tag acme.com

# Clear a tag (pass empty string)
python scripts/fofa_smart.py cache-tag --hash h1 --tag ""
```

| Param | Required | Description |
|-------|----------|-------------|
| `--hash` | Yes | Query hash to tag |
| `--tag` | Yes | Target/label to assign (empty string clears) |

Returns `{"tagged": true, "query_hash": "h1", "tag": "acme.com"}`. Unknown hash → `NOT_FOUND` (4004).

### correlate — Cross-query correlation & de-duplication

Merges results from multiple cached queries, de-duplicating by a key field (default `ip`). All work happens in SQLite — zero API calls, zero F-points. Use after multi-dimensional searches to find overlaps and unique assets.

Accepts `--hashes` (explicit comma-separated list) **or** `--tag` (expand to all queries tagged with one assessment target). `--tag` is the resilient path — it survives context compression that would otherwise wipe the hash list.

```
python scripts/fofa_smart.py correlate --hashes "h1,h2,h3" --key ip
# Or by assessment target tag (resilient to context compression):
python scripts/fofa_smart.py correlate --tag acme.com --key ip
```

| Param | Description |
|-------|-------------|
| `--hashes` | Comma-separated query hashes (min 2). Mutually alternative with `--tag`. |
| `--tag` | Correlate ALL queries tagged with this target (alternative to `--hashes`). |
| `--key` | De-duplication key field (default: `ip`; supports any indexed field) |

Returns unique count, duplicates removed, per-query breakdown, and an overlap matrix (diagonal = per-query unique count, off-diagonal = shared key count):
```json
{
  "__fofa__": true,
  "error": false,
  "total_unique": 342,
  "duplicates_removed": 58,
  "key": "ip",
  "per_query": [
    {"query_hash": "h1", "query_raw": "domain=\"acme.com\"", "total": 120, "unique_by_key": 118},
    {"query_hash": "h2", "query_raw": "cert=\"acme.com\"", "total": 280, "unique_by_key": 265}
  ],
  "overlap_matrix": [[118, 41], [41, 265]]
}
```

### report — Aggregated summary report

Generates a full summary across multiple cached queries: asset counts, port/country/protocol/server distributions, high-risk exposed ports, and admin panels. All local, zero F-point cost. Use as the final step of any assessment.

```
python scripts/fofa_smart.py report --hashes "h1,h2,h3"
# Or by assessment target tag:
python scripts/fofa_smart.py report --tag acme.com
# Override high-risk ports / admin keywords for a custom assessment scope:
python scripts/fofa_smart.py report --tag acme.com --high-risk-ports 22,23,3389,2375 --admin-keywords "admin,login,管理"
```

| Param | Description |
|-------|-------------|
| `--hashes` | Comma-separated query hashes (min 1). Mutually alternative with `--tag`. |
| `--tag` | Report on ALL queries tagged with this target (alternative to `--hashes`). |
| `--high-risk-ports` | Override the default high-risk port list (comma-separated ints). Default covers SSH/Telnet/RDP/VNC/DBs/caches/devops (16 ports). |
| `--admin-keywords` | Override admin-panel title keywords (comma-separated). Default covers CN+EN panel/product names. |
| `--limit` / `-n` | Cap on `high_risk_ports` / `admin_panels` detail rows (default 100). Lower this when context is tight. |

Returns:
```json
{
  "__fofa__": true,
  "error": false,
  "total_assets": 500,
  "total_unique_ips": 342,
  "by_port": [{"port": 443, "count": 180}, {"port": 80, "count": 120}],
  "by_country": [{"country": "CN", "count": 300}, {"country": "US", "count": 50}],
  "by_protocol": [{"protocol": "https", "count": 180}],
  "by_server": [{"server": "nginx", "count": 200}],
  "high_risk_ports": [{"ip": "1.2.3.4", "port": 3306, "host": "db.acme.com"}],
  "admin_panels": [{"ip": "5.6.7.8", "host": "admin.acme.com", "title": "管理后台"}],
  "per_query": [{"query_hash": "h1", "query_raw": "domain=\"acme.com\"", "total": 120}]
}
```

High-risk ports detected: 3389 (RDP), 22 (SSH), 3306 (MySQL), 6379 (Redis), 27017 (MongoDB), 9200 (Elasticsearch), 5900 (VNC), 5432 (PostgreSQL).
Admin panel keywords: 管理, admin, login, 后台, dashboard, console, manage.

### audit-log — View operation audit trail

```
python scripts/fofa_smart.py audit-log
python scripts/fofa_smart.py audit-log --limit 20
python scripts/fofa_smart.py audit-log --command search
```

| Param | Description |
|-------|-------------|
| `--limit` / `-n` | Max entries to return (default 50) |
| `--command` / `-c` | Filter by command name (e.g. search, info, cache-read) |

Returns recent audit log entries with timestamp, command, query, result code, and duration:
```json
{
  "__fofa__": true,
  "error": false,
  "total": 5,
  "entries": [
    {
      "timestamp": "2026-06-14 22:30:00",
      "command": "search",
      "query_hash": "abc123...",
      "query_raw": "domain=\"example.com\"",
      "params": "{\"page\": 1, \"size\": 100}",
      "result_code": 0,
      "duration_ms": 523
    }
  ]
}
```

### audit-clean — Purge old audit log entries

```
python scripts/fofa_smart.py audit-clean
python scripts/fofa_smart.py audit-clean --days 30
```

| Param | Description |
|-------|-------------|
| `--days` / `-d` | Keep last N days (default 30) |

Deletes audit log rows older than the cutoff. Returns the number of deleted entries:
```json
{
  "__fofa__": true,
  "error": false,
  "deleted": 42,
  "cutoff": "2026-05-23 21:31:00"
}
```
