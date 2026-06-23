o---
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
    - 资产暴露面
    - 暴露面
    - 暴露面测绘
    - fofa搜索
    - 指纹识别
    - 漏洞测绘
    - 威胁情报
    - icon_hash
    - JARM
    - 证书搜索
    - ICP备案
    - 网络安全评估
    - 安全评估
    - 子域名
    - 子域名发现
    - C2追踪
    - 钓鱼检测
    - 资产盘点
    - 攻击面
    - attack surface
  scenarios:
    - User asks about asset discovery for a domain/IP/organization
    - User wants to find exposed services, databases, or components
    - User needs vulnerability impact assessment (CVE, component version)
    - User requests fingerprint-based identification (favicon, JARM, banner)
    - User asks about statistical distribution of internet assets
    - User performs threat intelligence (phishing, C2, suspicious infrastructure)
    - User wants to correlate assets across dimensions (domain→IP→other domains)
    - User requests full exposure assessment for an organization
    - User wants to enumerate all subdomains of a target
    - User asks about attack surface mapping
    - User wants to assess security exposure of their own assets
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
- `FOFA_FPOINTS_BUDGET` — session-level F-point budget (int). When set, paginated requests are allowed without per-request AI confirmation as long as cumulative estimated spend stays under the budget. Spent total persists across CLI invocations via a state file. AI must still inform the user of total expected spend before starting a multi-search playbook.
- `FOFA_ALLOW_FPOINTS` — set to `true` to bypass the code-level hard block on pagination (per-request authorization mode). See note below.

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
- **For exposure assessment / asset inventory requests**: ALWAYS follow the Playbooks in "Asset Discovery Playbooks" section — never just run a single `search`. Multi-dimensional coverage is mandatory.
- **For subdomain enumeration**: Run ALL techniques in Playbook 4, not just `host=".target.com"`. Certificate SAN and CNAME techniques find subdomains DNS misses.
- **Before paginated (paid) searches**: Always run `stats` first to estimate scope. If >100 results, warn user about F-point cost and ask for authorization.

## Intent → Command Mapping

| User Intent | Command | Playbook |
|-------------|---------|----------|
| Find assets under a domain/IP | `search` | — |
| Find exposed services/components | `search` | — |
| Full exposure assessment for org | `search` + `stats` | Playbook 1 (7 dimensions) |
| Vulnerability impact assessment | `search --full` | Playbook 2 |
| Threat intel / C2 hunting | `search` | Playbook 3 |
| Enumerate all subdomains | `search` + `stats` | Playbook 4 (6 techniques) |
| Fingerprint identification | `search` | Playbook 5 |
| Assets matching a fingerprint | `search` | — |
| Distribution of a dimension | `stats` | — |
| Details of a specific IP/domain | `host` | — |
| Check account status | `info` | — |
| Re-view previous query results | `cache-read` | — |
| Cross-query correlation & de-dup | `correlate` | — |
| Aggregated summary report | `report` | — |
| View operation history | `audit-log` | — |
| Purge old audit log entries | `audit-clean` | — |


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

## Asset Discovery Playbooks

Detailed playbooks have been extracted to **[docs/playbooks.md](docs/playbooks.md)** to keep this instruction file concise. Read that document before any reconnaissance task.

It contains:
- The 7-Dimension Asset Discovery Model
- Query Optimization techniques (how to find more than others)
- Playbook 1: Full Exposure Assessment (Organization-Wide)
- Playbook 2: Vulnerability Impact Assessment
- Playbook 3: Threat Intelligence & C2 Hunting
- Playbook 4: Subdomain Discovery (6 techniques)
- Playbook 5: Fingerprint Identification & Component Mapping
- Asset De-duplication Strategy
- Risk Prioritization Framework
- F-Point Budget Strategy for Playbooks
- Cross-Engine Validation

## Database

Auto-created on first run at `data/fofa_cache.db`:

- `query_cache` — query metadata, PK: query_hash (SHA-256)
- `query_result` — one row per result, `data` column stores full JSON, indexed columns for ip/port/host/banner/jarm/icp/cname
- `info_cache` — account info cache, TTL 5 min
- `host_cache` — `host` and `stats` response cache, TTL 5 min (free endpoints)
- `audit_log` — operation audit trail with timestamp, command, query, result code, and duration

A separate state file `data/fpoints_state.json` tracks cumulative F-point spend when `FOFA_FPOINTS_BUDGET` is set (not a DB table — it must persist across CLI invocations within a session).

## Workflow

### On conversation start

1. Run `python scripts/fofa_smart.py info` to verify account
2. If **registered user (no API access)**, inform user and refuse all API operations

### On user query

1. **Identify intent** → pick command per "Intent → Command Mapping"
2. **Build query** → per "Query Construction"
3. **Show & explain the query** — explain each part in plain language (e.g., `host=".edu"` → "hostname ending in .edu"), do NOT copy-paste from syntax reference
4. Run the command (add `--no-cache` if user says "fresh data"/"re-query"). For any multi-search assessment, pass `--tag <target>` so later correlate/report work without tracking hashes.
5. Show summary (total + preview), **never dump full results**
6. For more data → `cache-read`
7. For correlation/de-dup → `correlate --tag <target> --key ip` (or `--hashes h1,h2,h3`)
8. For summary report → `report --tag <target>` (or `--hashes h1,h2,h3`)
9. For correlation/pivoting → suggest multi-step workflow per "Penetration Testing Workflows"

### Multi-turn state tracking

Search results include `query_hash`. For a single lookup, track the latest `query_hash` in conversation. For any multi-search assessment, **prefer `--tag <target>`** over hash tracking — it is resilient to context compression (see below).

- "Next page" → `cache-read --hash <hash> -p 2`
- "Search with different criteria" → new `search --tag <target>`, update `query_hash`
- "Correlate / deduplicate results" → `correlate --tag <target> --key ip`
- "Generate a report" → `report --tag <target>`
- "Filter them" → `cache-read --hash <hash> --filter "..."`

### Context compression recovery (IMPORTANT)

Long assessment workflows trigger context compression, which wipes the in-memory `query_hash` list you were tracking. **This must never force an F-point re-fetch** — the data is already cached. Recovery primitives:

- `cache-list --tag <target>` — re-surface every hash, `query_raw`, `tag`, and `result_count` for one assessment target
- `cache-list --query <substring>` — find queries by substring of `query_raw` (e.g. a domain)
- `cache-tag --hash <h> --tag <target>` — retroactively tag searches you performed *without* `--tag`, so `correlate --tag` / `report --tag` still work — no re-fetch, no re-spend

Once queries are tagged, `correlate --tag <target>` and `report --tag <target>` read straight from the cache. The hash list is never needed again.

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
| `{"__fofa__": true, "error": true, "code": 4004}` | Not found — e.g. `--tag` with no cached queries, or `cache-tag`/`cache-delete` on an unknown hash. Run `cache-list` to see what's cached |
| `{"__fofa__": true, "error": true, "code": 5001}` | Internal error — display `msg` to user |
| FOFA API 820001 in msg | **Field permission denied** — user's FOFA tier lacks access to fields like `icon_hash`, `body_hash`, `mf_hash`, `product`, `category`. Drop the restricted field and retry with alternative fields (e.g., use `cert`/`jarm`/`banner` instead of `icon_hash`). Warn user which fields require higher FOFA tier. |
| `{"__fofa__": true, "error": true, ...}` | Unknown error — display `msg` to user |
| Non-zero exit code | Script crash — ask user to check environment |

> **Note**: All JSON outputs include `"__fofa__": true` as a marker to reliably distinguish FOFA output from other stdout content.

## F-Point Budget Guard (CRITICAL)

```
Rule: page=1 is free, page>1 costs F-points
Hard block: NEVER pass --allow-fpoints unless user explicitly authorizes
```

### Authorization Modes (in priority order)

1. **Session budget** (`FOFA_FPOINTS_BUDGET=N` env var): allows up to N F-points per session without per-request confirmation. Best for multi-step assessments (Playbook 1). AI should still inform the user that pagination is in progress.
2. **Per-request** (`--allow-fpoints`): single-request authorization. Next paginated request requires new confirmation.
3. **Global allow** (`FOFA_ALLOW_FPOINTS=true`): bypasses code-level block. AI must still notify user before each paginated request.

### Rules

- AI must **never** add `--allow-fpoints` or set `FOFA_FPOINTS_BUDGET` on its own
- On F-point denial (code 2001), explain cost and ask for authorization
- For multi-step assessments, ask user to set `FOFA_FPOINTS_BUDGET=1000` once to avoid confirmation churn
- `stats`, `host`, `correlate`, and `report` are free — no F-point cost
- `correlate` and `report` operate entirely on local SQLite cache — use them to build reports without API calls

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
- Direct users to `cache-read` for full data

## Cache

- Same conditions (query + fields + full + page + size) hit hash → use cache
- TTL: `full=false` → 24h, `full=true` → 7 days
- Exact hash match only, no partial/subset matching
- **Expired cache** → `search` treats as miss and re-queries from API; `cache-read` still returns data with `cache_expired: true` flag
- When `cache_expired: true` appears, warn user that data may be stale and suggest re-running `search`
- **Covering cache optimization** → when requesting page>1, the system automatically checks if an existing page=1 cache already has enough data to serve the request, avoiding redundant API calls. If used, the response includes `"covering_cache": true`

## Command Reference

Full parameter reference and example outputs for all 14 subcommands have been extracted to **[docs/command-reference.md](docs/command-reference.md)**.

Quick summary of available commands:

| Command | Purpose | F-point cost |
|---------|---------|--------------|
| `info` | Account info (cached 5 min) | Free |
| `search` | Asset search with cache + F-point guard | page=1 free, page>1 costs |
| `stats` | Statistical aggregation (cached 5 min) | Free |
| `host` | Host details (cached 5 min) | Free |
| `cache-read` | Read/filter cached results | Free (local) |
| `cache-delete` | Delete a cached query | Free (local) |
| `cache-clean` | Purge old cache entries | Free (local) |
| `cache-stats` | Show cache row counts | Free (local) |
| `cache-list` | List cached queries (recover hashes for correlate/report) | Free (local) |
| `cache-tag` | Tag (or re-tag) an already-cached query — group untagged searches | Free (local) |
| `correlate` | Cross-query correlation & de-dup (`--hashes` or `--tag`) | Free (local) |
| `report` | Aggregated summary report (`--hashes` or `--tag`) | Free (local) |
| `audit-log` | View operation audit trail | Free (local) |
| `audit-clean` | Purge old audit log entries | Free (local) |

For parameter details, examples, and sample JSON outputs, see the linked document.

## Usage Boundaries

AI should refuse or warn in these cases:

- **Mass scanning**: Warn against bulk scanning of unrelated targets
- **Illegality**: Refuse queries tied to unauthorized penetration testing or attacks
- **Sensitive data**: Remind user of data protection obligations when results contain personal data
- **Size limit**: `-s` must not exceed 10000; FOFA API truncates beyond this
