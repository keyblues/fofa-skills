---
name: fofa-skills
description: FOFA cyberspace search engine skill — asset discovery, vulnerability mapping, threat intelligence, fingerprinting, and statistical aggregation.
version: "0.1.0"
triggers:
  keywords:
    - fofa
    - FOFA
    - 网络空间搜索
    - 资产测绘
    - 测绘
    - 资产发现
    - fofa搜索
    - 指纹识别
    - 漏洞测绘
    - 威胁情报
    - icon_hash
    - JARM
    - 证书搜索
    - ICP备案
  scenarios:
    - User asks about asset discovery for a domain/IP/organization
    - User wants to find exposed services, databases, or components
    - User needs vulnerability impact assessment (CVE, component version)
    - User requests fingerprint-based identification (favicon, JARM, banner)
    - User asks about statistical distribution of internet assets
    - User performs threat intelligence (phishing, C2, suspicious infrastructure)
    - User wants to correlate assets across dimensions (domain→IP→other domains)
compatibility:
  claude_code: ">=1.0.0"
  python: ">=3.9"
  skill_version: "0.1.0"
---

# FOFA Search Skill

FOFA cyberspace search engine skill. Covers asset discovery, vulnerability mapping, threat intelligence, fingerprinting, and statistical aggregation.

## When to Activate This Skill

Activate this skill when the user's request involves any of:

- Searching for internet-facing assets (domains, IPs, services, ports)
- Vulnerability impact assessment / exposure checking
- Fingerprint identification (favicon hash, JARM, banner, certificate)
- Statistical analysis of internet asset distribution
- Threat intelligence (phishing detection, C2 identification, suspicious infrastructure)
- Cross-correlation / pivoting through shared infrastructure
- Any explicit mention of "FOFA", "网络空间搜索", "资产测绘", "fofa搜索"

Do **NOT** activate for:
- General web search queries (use web search tools instead)
- Non-cyberspace reconnaissance questions
- Questions solely about other search engines (Shodan, Censys) — unless user explicitly asks to cross-reference with FOFA

## Version Compatibility

- Skill version: **0.1.0** (must match `fofa-skills --version` output)
- Compatible with: Claude Code >= 1.0.0, Python >= 3.9
- If `--version` output doesn't match this SKILL.md's stated version, warn the user of potential inconsistency and suggest updating

## Important

All commands must be run from the project root (where `SKILL.md` resides).

## Prerequisites

- Python 3.9+ (stdlib only, zero pip dependencies)
- FOFA API KEY (32-char hex from [FOFA Personal Center](https://fofa.info))

### Verify Setup

```bash
python scripts/fofa_smart.py --version   # fofa-skills 0.1.0
python scripts/fofa_smart.py info        # verify key + account
```

### KEY Configuration

Lookup order:
1. Environment variable `FOFA_KEY`
2. `.env` file in project root: `FOFA_KEY=xxx`

If script returns `{"__fofa__": true, "error": true, "code": 1002}`:
- Ask user to get key from https://fofa.info
- Write to `.env`: `echo "FOFA_KEY=xxx" > .env`
- Retry the command

Optional env vars:
- `FOFA_DB_PATH` — SQLite path, default `./data/fofa_cache.db`
- `FOFA_BASE_URL` — API base URL, default `https://fofa.info/api/v1`

> **Note on `FOFA_ALLOW_FPOINTS=true`**: Even when set, AI must still notify the user before every paginated request that F-points will be consumed and wait for confirmation. This env var only bypasses the code-level hard block, not the AI-level confirmation obligation.

## Skill Boundaries & Refusal Rules

### Must Refuse
- **Unauthorized attack planning**: Queries clearly intended for planning attacks on specific targets without authorization context
- **Mass surveillance**: Bulk collection of personal data without legitimate security research context
- **Illegal activity**: Any query tied to unauthorized penetration testing or illegal operations

### Must Warn
- **Mass scanning**: Warn when query scope is extremely broad and may indicate indiscriminate scanning
- **Sensitive data**: Remind user of data protection obligations when results contain personal data (names, emails, credentials)
- **F-point consumption**: Always warn before any operation that costs F-points

### Behavioral Rules
- When uncertain which subcommand to use, prefer `stats` (free) over `search` for count-only questions
- When `search` returns no results, suggest alternative query patterns before giving up
- Always explain query parts in plain language — never raw-paste FOFA syntax to user
- When multiple queries are needed, batch them and explain the workflow
- When user is doing comprehensive reconnaissance, suggest cross-referencing with Censys/Shodan for validation (FOFA's strength is Chinese internet space; other engines may have better global coverage)

## Intent → Command Mapping

| User Intent | Command | Example |
|-------------|---------|---------|
| Find assets under a domain/IP | `search` | "What services does example.com have?" |
| Find exposed services/components | `search` | "Find exposed MySQL on the internet" |
| Vulnerability impact assessment | `search --full` | "What assets are affected by Log4j?" |
| Assets matching a fingerprint | `search` | "Sites with icon_hash xxx" |
| Distribution of a dimension | `stats` | "Port distribution of Apache" |
| Details of a specific IP/domain | `host` | "What's running on 1.1.1.1?" |
| Check account status | `info` | "How many F-points do I have?" |
| Re-view previous query results | `cache-read` | "Show me that search again" |
| Export results to file | `cache-export` | "Export results as CSV" |
| View operation history | `audit-log` | "What queries have been run?" |

### `search` vs `host`

- **`search`**: Find assets matching conditions → returns a list. Use when user asks "what assets match X?"
- **`host`**: Get full profile of one IP/domain → returns all services on that host. Use when user asks "what's running on this machine?"

Example: "Check 1.1.1.1" → `host` for full profile; `search -q 'ip="1.1.1.1"'` if it's just a filter condition.

### `search` vs `stats`

- **`search`**: When user wants a concrete asset list
- **`stats`**: When user only wants distribution counts (e.g., "how many per port"). Free, no F-point cost.

## Query Construction

Convert natural language to FOFA query:

1. **Extract entities**: Identify IPs, domains, ports, component names, keywords
2. **Map to fields**: Match entities to FOFA syntax fields
3. **Combine**: Use `&&` (AND) / `||` (OR) to join conditions

### Common Patterns

| User Says | Mapping | FOFA Query |
|-----------|---------|------------|
| "Assets of example.com" | domain → `domain` | `domain="example.com"` |
| "Exposed MySQL" | protocol → `protocol` | `protocol="mysql"` |
| "What's on this IP range" | IP → `ip`, supports CIDR | `ip="1.1.1.0/24"` |
| "Sites with 'admin' in title" | keyword → `title` | `title="admin"` |
| "Apache sites in China" | app + country | `app="Apache" && country="CN"` |
| "Nginx 1.18 servers" | server header | `server="nginx/1.18.0"` |
| ".edu domains on port 443" | host suffix + port | `host=".edu" && port="443"` |
| "Sites with a specific SSL cert" | cert → `cert` | `cert="CN=*.example.com"` |
| "Sites with a specific favicon" | favicon → `icon_hash` | `icon_hash="-247388890"` |
| "Assets after Jan 2024" | time range | `after="2024-01-01" && domain="example.com"` |
| "Assets before a certain date" | time range | `before="2024-12-31" && app="Apache"` |
| "JARM fingerprint match" | JARM → `jarm` | `jarm="29d29d15d29d29d000..." && port="443"` |
| "ICP filing number" | ICP → `icp` | `icp="京ICP备12345678"` |
| "Certificate subject detail" | cert subject → `cert.subject` | `cert.subject="CN=*.example.com"` |
| "Certificate issuer" | cert issuer → `cert.issuer` | `cert.issuer="CN=Let's Encrypt"` |
| "CNAME record" | CNAME → `cname` | `cname="cdn.example.com"` |

### Construction Rules

- Prefer precise fields over fuzzy ones (`domain=` > `host=`, `app=` > `title=`, `cert.subject=` > `cert=`)
- Use ≥2 conditions to narrow scope when possible
- Only add `--full` when user explicitly requests full historical data
- `-s` max 10000
- For time-bounded queries, use `after` and `before` fields to narrow scope

## Penetration Testing Workflows

### Cross-Correlation Analysis (Pivoting)

Discover related assets by pivoting through shared infrastructure. This is a common workflow in penetration testing and threat intelligence:

1. **Domain → IP → Other Domains**: Find all domains hosted on the same IP
2. **Certificate Correlation**: Find all hosts sharing the same certificate
3. **JARM-based C2 Detection**: Identify C2 infrastructure with matching TLS fingerprints
4. **Banner Fingerprinting**: Identify services by their banner responses

Example multi-step correlation workflow:

```bash
# Step 1: Find IPs for a domain
python scripts/fofa_smart.py search -q 'domain="target.com"' -f "ip,domain,host"

# Step 2: Pivot — find OTHER domains on those IPs (same infrastructure)
python scripts/fofa_smart.py search -q 'ip="1.2.3.4" && domain!="target.com"' -f "domain,host,title"

# Step 3: Certificate correlation — find all hosts sharing the same certificate
python scripts/fofa_smart.py search -q 'cert.subject="CN=*.target.com"' -f "host,ip,title"

# Step 4: JARM fingerprint — identify similar infrastructure
python scripts/fofa_smart.py search -q 'jarm="29d29d15d29d29d000..." && country="CN"' -f "host,ip,port"
```

### C2 Detection via JARM

JARM fingerprinting helps identify C2 infrastructure. Common C2 frameworks have known JARM hashes:

```bash
# Search by known C2 JARM hash
python scripts/fofa_smart.py search -q 'jarm="07d14d16d21d21d000..." && port="443"'

# Combine with other indicators for higher confidence
python scripts/fofa_smart.py search -q 'jarm="07d14d16d21d21d000..." && cert.issuer="CN=Unknown"'
```

### Deep Certificate Analysis

Fine-grained certificate queries for threat intelligence:

```bash
# Find all certificates issued by a specific CA for a domain
python scripts/fofa_smart.py search -q 'cert.subject="O=Target Org" && cert.issuer="CN=DigiCert"'

# Find self-signed certificates for a domain (potential staging infrastructure)
python scripts/fofa_smart.py search -q 'cert.subject="CN=*.target.com" && cert.issuer="CN=*.target.com"'

# Broad cert search
python scripts/fofa_smart.py search -q 'cert="CN=*.suspicious.com"'
```

### ICP Filing Correlation

For Chinese internet assets, ICP filing numbers can link domains to organizations:

```bash
# Find all domains under the same ICP filing
python scripts/fofa_smart.py search -q 'icp="京ICP备12345678"' -f "domain,host,title"
```

### Cross-Engine Validation Tips

For comprehensive reconnaissance, consider cross-referencing FOFA results with:

- **Censys**: Validates TLS certificate data and host service enumeration. Strong for academic/research networks.
- **Shodan**: Confirms banner/service fingerprints and industrial system exposure. Strong for IoT/ICS.
- **FOFA's strength**: Chinese internet space coverage, ICP filing data, and large historical dataset.

> Note: This skill only covers FOFA. Cross-referencing requires separate tools, but AI should suggest it when appropriate.

## Database

Auto-created on first run at `data/fofa_cache.db`:

- `query_cache` — query metadata, PK: query_hash (SHA-256)
- `query_result` — one row per result, `data` column stores full JSON, indexed columns for ip/port/host/banner/jarm/icp/cname
- `info_cache` — account info cache, TTL 5 min
- `audit_log` — operation audit trail with timestamp, command, query, result code, and duration

## Workflow

### On conversation start

1. Run `python scripts/fofa_smart.py info` to verify account
2. If **registered user (no API access)**, inform user and refuse all API operations

### On user query

1. **Identify intent** → pick command per "Intent → Command Mapping"
2. **Build query** → per "Query Construction"
3. **Show & explain the query** — explain each part in plain language (e.g., `host=".edu"` → "hostname ending in .edu"), do NOT copy-paste from syntax reference
4. Run the command (add `--no-cache` if user says "fresh data"/"re-query")
5. Show summary (total + preview), **never dump full results**
6. For more data → `cache-read`
7. For export → `cache-export`
8. For correlation/pivoting → suggest multi-step workflow per "Penetration Testing Workflows"

### Multi-turn state tracking

Search results include `query_hash`. AI must track the latest `query_hash` in conversation:

- "Next page" → `cache-read --hash <hash> -p 2`
- "Search with different criteria" → new `search`, update `query_hash`
- "Export those results" → `cache-export --hash <hash>`
- "Filter them" → `cache-read --hash <hash> --filter "..."`

## Error Handling

| Case | Action |
|------|--------|
| `{"__fofa__": true, "error": false, ...}` | Success, display results |
| `{"__fofa__": true, "error": true, "code": 1001}` | API/network error, retry after checking network |
| `{"__fofa__": true, "error": true, "code": 1002}` | Auth failed, check FOFA_KEY (must be 32-char hex) |
| `{"__fofa__": true, "error": true, "code": 1003}` | Rate limited, wait and retry |
| `{"__fofa__": true, "error": true, "code": 1004}` | Network unreachable, check connection |
| `{"__fofa__": true, "error": true, "code": 2001}` | F-point denied, explain and ask for authorization |
| `{"__fofa__": true, "error": true, "code": 2002}` | Registered user, no API access — suggest upgrade |
| `{"__fofa__": true, "error": true, "code": 2003}` | F-point balance insufficient — suggest recharge |
| `{"__fofa__": true, "error": true, "code": 3001}` | Cache miss — re-run `search` |
| `{"__fofa__": true, "error": true, "code": 4001}` | Invalid parameter — check command arguments |
| `{"__fofa__": true, "error": true, "code": 5001}` | Internal error — display `msg` to user |
| `{"__fofa__": true, "error": true, ...}` | Unknown error — display `msg` to user |
| Non-zero exit code | Script crash — ask user to check environment |

> **Note**: All JSON outputs include `"__fofa__": true` as a marker to reliably distinguish FOFA output from other stdout content.

## F-Point Budget Guard (CRITICAL)

```
Rule: page=1 is free, page>1 costs F-points
Hard block: NEVER pass --allow-fpoints unless user explicitly authorizes
```

- AI must **never** add `--allow-fpoints` on its own
- On F-point denial (code 2001), explain cost and ask for authorization
- Authorization is per-request only; next paginated request requires new confirmation
- `stats` and `host` are free — no F-point cost
- Even with `FOFA_ALLOW_FPOINTS=true`, AI must still notify user before each paginated request

## Output Rules

### Must include

- Original query string
- Query explanation (plain language per part, e.g., `host=".edu"` → "hostnames ending in .edu", `port="443"` → "port 443")
- Total result count
- Current page / total pages
- Whether from cache
- F-point cost (labeled as "estimated")

### Must NOT

- **Never dump full results into context**
- Show at most 20 preview rows
- Direct users to `cache-read` or `cache-export` for full data

## Cache

- Same conditions (query + fields + full + page + size) hit hash → use cache
- TTL: `full=false` → 24h, `full=true` → 7 days
- Exact hash match only, no partial/subset matching
- **Expired cache** → `search` treats as miss and re-queries from API; `cache-read` / `cache-export` still return data with `cache_expired: true` flag
- When `cache_expired: true` appears, warn user that data may be stale and suggest re-running `search`
- **Covering cache optimization** → when requesting page>1, the system automatically checks if an existing page=1 cache already has enough data to serve the request, avoiding redundant API calls. If used, the response includes `"covering_cache": true`

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
  "fpoints_consumed": 0
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

### stats — Statistical aggregation (free, no F-point cost)

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
  "distinct": {"ip": 1234},
  "aggs": [{"count": 500, "port": "80"}, {"count": 300, "port": "443"}]
}
```

### host — Host details (free, no F-point cost)

```
python scripts/fofa_smart.py host --host "1.1.1.1"
python scripts/fofa_smart.py host --host "1.1.1.1" --detail
```

| Param | Required | Description |
|-------|----------|-------------|
| `--host` | Yes | Target IP or domain |
| `--detail` | No | Include per-port protocol/banner/cert details |

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
  "port": [80, 443],
  "protocol": ["http", "https"]
}
```

With `--detail`, adds a `details` list with per-port protocol, banner, and certificate info:
```json
{
  "__fofa__": true,
  "error": false,
  "host": "1.1.1.1",
  "ip": "1.1.1.1",
  "asn": 13335,
  "org": "Cloudflare, Inc.",
  "country_name": "United States",
  "port": [80, 443],
  "protocol": ["http", "https"],
  "details": [
    {"port": 80, "protocol": "http", "banner": "HTTP/1.1 ..."},
    {"port": 443, "protocol": "https", "banner": "HTTP/1.1 ...", "cert": {...}}
  ]
}
```

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

### cache-export — Export cached results

```
python scripts/fofa_smart.py cache-export --hash "abc123..."
python scripts/fofa_smart.py cache-export --hash "abc123..." --format csv -o result.csv
```

| Param | Description |
|-------|-------------|
| `--hash` | Query hash |
| `--format` / `-f` | `json` (default) or `csv` |
| `--output` / `-o` | Output path; auto-generated under `data/` if omitted |

### cache-clean — Purge old cache

```
python scripts/fofa_smart.py cache-clean --days 30
```

### cache-stats — Cache statistics

```
python scripts/fofa_smart.py cache-stats
```

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

## FOFA Query Syntax Reference

> This reference is for AI to understand FOFA syntax. When explaining queries to users, use plain language per part — do NOT copy-paste from this table.

### Basic Fields

| Syntax | Example | Description |
|--------|---------|-------------|
| `ip` | `ip="1.1.1.1"` | IP match, supports CIDR (`ip="1.1.1.0/24"`) |
| `port` | `port="443"` | Port number |
| `protocol` | `protocol="https"` | Protocol type |
| `host` | `host=".edu"` | Hostname match; leading `.` matches all hostnames ending with that suffix |
| `domain` | `domain="example.com"` | Domain exact match |
| `title` | `title="admin"` | Page title keyword |
| `server` | `server="Apache"` | Server software |
| `body` | `body="login"` | HTTP response body |
| `header` | `header="nginx"` | HTTP response header |
| `banner` | `banner="SSH-2.0"` | Service banner |
| `cert` | `cert="CN=*.google.com"` | SSL certificate (broad match across all cert fields) |
| `cert.subject` | `cert.subject="CN=*.example.com"` | Certificate subject — more granular than `cert` |
| `cert.issuer` | `cert.issuer="CN=Let's Encrypt"` | Certificate issuer / CA |
| `icon_hash` | `icon_hash="-247388890"` | Favicon hash |
| `jarm` | `jarm="29d29d15d29d29d000..."` | TLS JARM fingerprint (useful for C2 detection) |
| `body_hash` | `body_hash="abc123"` | HTTP response body hash |
| `cname` | `cname="cdn.example.com"` | CNAME DNS record |

### Asset & Ownership

| Syntax | Example | Description |
|--------|---------|-------------|
| `app` | `app="Apache"` | Component/application |
| `product` | `product="Apache-HTTPD"` | Product ID (Pro+ required) |
| `category` | `category="service"` | Asset category (Pro+ required) |
| `os` | `os="Linux"` | Operating system |
| `asn` | `asn="15169"` | AS number |
| `org` | `org="Google LLC"` | Organization |
| `country` | `country="CN"` | Country (ISO code) |
| `city` | `city="Beijing"` | City |
| `type` | `type="service"` | Asset type |
| `icp` | `icp="京ICP备12345678"` | ICP registration number (China) |
| `mf_hash` | `mf_hash="xxx"` | Multi-function fingerprint hash |

### Logic Operators

| Syntax | Example | Description |
|--------|---------|-------------|
| `&&` | `port="443" && country="CN"` | AND |
| `\|\|` | `port="80" \|\| port="443"` | OR |
| `()` | `(app="nginx" \|\| app="apache") && country="US"` | Grouping |

### Time Range

| Syntax | Example | Description |
|--------|---------|-------------|
| `after` | `after="2024-01-01"` | After this date |
| `before` | `before="2024-12-31"` | Before this date |

## Usage Boundaries

AI should refuse or warn in these cases:

- **Mass scanning**: Warn against bulk scanning of unrelated targets
- **Illegality**: Refuse queries tied to unauthorized penetration testing or attacks
- **Sensitive data**: Remind user of data protection obligations when results contain personal data
- **Size limit**: `-s` must not exceed 10000; FOFA API truncates beyond this
