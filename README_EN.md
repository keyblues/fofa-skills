s'k# fofa-skills

<p align="center">
  <b>FOFA Cyberspace Search Engine · Claude Code Skill</b><br>
  Asset discovery · vulnerability mapping · threat intelligence · fingerprinting<br>
  with caching, F-point budget guard, and zero pip dependencies.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue" alt="Python versions">
  <img src="https://img.shields.io/badge/dependencies-zero-brightgreen" alt="Zero pip dependencies">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
  <a href="README.md">中文</a>
</p>

---

## Why fofa-skills?

FOFA has a powerful API, but using it effectively from an AI assistant involves real engineering problems:

- **Context explosion** — a single query can return 10,000 results. Dumping them into the LLM context is wasteful and expensive.
- **F-point budget** — pagination costs money. An AI that blindly fetches page after page can burn through F-points in seconds.
- **Duplicate API calls** — the same query run twice wastes quota and time.
- **Rate limits** — FOFA enforces 1 req/s. Burst requests get 429'd.

fofa-skills solves all of these. It is a **Claude Code Skill + tool-script bundle** that wraps the FOFA API with caching, rate limiting, a hard F-point guard, and AI-optimized output.

## Features

| Feature | How |
|---------|-----|
| **F-point Budget Guard** | Page > 1 is blocked by default. Only proceeds when user explicitly authorizes F-point spend |
| **Hash-based Caching** | SHA-256(query + fields + page + size) → SQLite. Exact-match reuse, no stale data confusion |
| **Summary-only Output** | Search returns metadata + 20-row preview. Full results live in SQLite, accessed via `cache-read` |
| **Rate Limiting** | Built-in 1-second interval + exponential backoff on 429 |
| **Account Info Caching** | 5-minute TTL — avoids extra API calls on every search |
| **Zero pip deps** | sqlite3, urllib, json, hashlib, argparse — all stdlib |
| **AI-First CLI** | Structured JSON on stdout. Designed for LLM tool-calling |

## Quick Start

```bash
git clone https://github.com/<user>/fofa-skills.git
cd fofa-skills

# Set API KEY (from https://fofa.info — Personal Center)
export FOFA_KEY="your_32_char_api_key"

# Verify account
python scripts/fofa_smart.py info

# Search — returns summary only, saves full results to cache
python scripts/fofa_smart.py search -q 'host=".edu" && port="443"' -f "ip,port,host,title"

# Read cached results with filtering
python scripts/fofa_smart.py cache-read --hash "<query_hash>" --filter "country=CN" -p 1 -s 50
```

## Usage Scenarios

### Asset Discovery
```bash
python scripts/fofa_smart.py search -q 'domain="example.com"'
python scripts/fofa_smart.py search -q 'protocol="mysql" && country="CN"'
python scripts/fofa_smart.py search -q 'ip="1.1.1.0/24"'
```

### Vulnerability Mapping
```bash
python scripts/fofa_smart.py search -q 'server="Apache/2.4.49"' --full
python scripts/fofa_smart.py search -q 'app="Log4j"'
```

### Threat Intelligence
```bash
python scripts/fofa_smart.py search -q 'cert="CN=*.suspicious-domain.com"'
```

### Fingerprinting
```bash
python scripts/fofa_smart.py search -q 'icon_hash="-247388890"'
python scripts/fofa_smart.py search -q 'header="nginx/1.18.0"'
```

### Statistics & Host Info
```bash
# Port distribution for a component
python scripts/fofa_smart.py stats -q 'app="Apache"' -f "port"

# Detailed host information
python scripts/fofa_smart.py host --host "1.1.1.1" --detail
```

## Version

```bash
python scripts/fofa_smart.py --version
# fofa-skills 0.1.0
```

## Architecture

```
┌─────────────────────────────────────────────────┐
│                 Claude Code / AI                 │
│          calls fofa_smart.py subcommands         │
└──────────────┬──────────────────────────────────┘
               │
     ┌─────────▼──────────┐
     │   fofa_smart.py    │  Orchestration CLI
     │   (10 subcommands)  │  · info / search / stats / host
     └──┬──────────────┬──┘  · cache-read / delete / export / clean / stats
        │              │     · audit-log
        │              │
   ┌────▼────┐   ┌─────▼──────┐
   │fofa_api │   │ fofa_cache │
   │ HTTP    │   │  SQLite    │
   │ retry   │   │  hash      │
   │ guard   │   │  filter    │
   └────┬────┘   └────────────┘
        │
   ┌────▼────┐
   │  FOFA   │
   │  API    │
   └─────────┘
```

## F-Point Budget Guard

This is a **hard safety lock**, not a configuration option.

```python
# fofa_api.py — every search() call
if page > 1 and not allow_fpoints:
    return {"error": True, "msg": "F-point spend denied", "code": 2001}
```

- **Default**: page 1 only, zero F-points consumed
- **To unlock**: user must explicitly authorize F-point consumption
- **Scope**: per-request. Unlocking one query does not unlock the next

## Caching Strategy

- **Exact hash match only** — query + fields + full + page + size all participate in the hash
- **No syntactic analysis** — `host=".edu"` and `host=".edu" && port="443"` are separate cache entries. Safe over clever.
- **Covering cache optimization** — when requesting page>1, automatically checks if an existing page=1 cache already has enough data to serve the request, avoiding redundant API calls
- **TTL**: `full=false` 24 hours, `full=true` 7 days
- **Account info**: separate cache, 5-minute TTL

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). PRs welcome — please keep it zero-dependency.

## License

MIT — see [LICENSE](LICENSE).
