# fofa-skills

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

## What is this

**fofa-skills** is a Claude Code / AI Agent Skill for the [FOFA](https://fofa.info) cyberspace search engine.

It solves four engineering problems that arise when letting AI call the FOFA API directly:

| Problem | Solution |
|---------|----------|
| **Context explosion** — a single query returns up to 10,000 rows, dumping them into the LLM is wasteful and expensive | Search returns only a summary + 20-row preview; full results live in SQLite, accessed via `cache-read` |
| **F-point budget burn** — pagination costs F-points; an AI paging blindly can exhaust the balance in seconds | `page > 1` is hard-blocked by default; requires explicit user authorization |
| **Duplicate API calls** — the same query hit repeatedly wastes quota and time | SHA-256 hash cache with exact-match reuse and covering-cache optimization |
| **Rate limits** — FOFA enforces 1 req/s; bursts get 429'd | Built-in 1-second throttle + exponential backoff on 429 |

## Features

- **F-point Budget Guard** — a hard safety lock, not a config switch; `page > 1` denied by default
- **Hash-based Caching** — SHA-256(query + fields + page + size) → SQLite, exact match
- **Summary-only Output** — search returns metadata + 20-row preview; full data read on demand
- **Rate Limiting** — 1-second interval + exponential backoff on 429
- **Account Info Caching** — 5-minute TTL avoids redundant info API calls
- **Audit Log** — every operation recorded; can be purged by date
- **Zero pip deps** — Python standard library only
- **AI-First CLI** — structured JSON on stdout, designed for LLM tool-calling

## Installation

```bash
git clone https://github.com/<user>/fofa-skills.git
cd fofa-skills

# Set API KEY (from https://fofa.info — Personal Center)
export FOFA_KEY="your_32_char_api_key"

# Verify account
python scripts/fofa_smart.py info
```

> You may also `pip install -e .` to register a global `fofa-skills` command, but this installs **no third-party packages** — it only registers the entry point.

## Architecture

```
┌─────────────────────────────────────────────────┐
│                 Claude Code / AI                 │
│          calls fofa_smart.py subcommands         │
└──────────────┬──────────────────────────────────┘
               │
     ┌─────────▼──────────┐
     │   fofa_smart.py    │  Orchestration CLI (14 subcommands)
     └──┬──────────────┬──┘
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

**14 subcommands**: `info` · `search` · `stats` · `host` · `cache-read` · `cache-delete` · `cache-clean` · `cache-stats` · `cache-list` · `cache-tag` · `correlate` · `report` · `audit-log` · `audit-clean`

## Project Structure

```
fofa-skills/
├── SKILL.md                      # Claude Code Skill instruction (concise)
├── docs/
│   ├── playbooks.md              # 5 asset discovery playbooks + 7-dimension model
│   ├── command-reference.md      # Full parameter reference for 14 subcommands
│   └── fofa-syntax.md            # FOFA query syntax reference
├── scripts/
│   ├── fofa_errors.py            # Unified JSON error envelope + stderr logging
│   ├── fofa_cache.py             # SQLite cache layer
│   ├── fofa_api.py               # API layer (throttle/retry/F-point guard/error detection)
│   └── fofa_smart.py             # CLI entry point
├── examples/
│   └── sample-outputs.txt        # Sample outputs
├── data/
│   └── fofa_cache.db             # Auto-created on first run
├── README.md                     # Project overview (Chinese)
├── README_EN.md                  # Project overview (English)
├── CHANGELOG.md                  # Version history
├── CONTRIBUTING.md               # Contribution guide
├── pyproject.toml                # Project metadata
└── LICENSE                       # MIT
```

## Design Principles

- **Zero dependencies** — stdlib only, clone and run, no environment pollution
- **Security first** — hard F-point block, audit log, built-in refusal rules
- **AI-friendly** — JSON output, `__fofa__` marker, summaries not full dumps
- **Exact caching** — only exact hash matching, no query splitting, safe over clever

> **Concurrency note**: built-in rate limiting (1 req/s) uses a single-process global variable, suitable for a single Claude Code session. Multi-process or multi-threaded embedding requires external rate limiting.

## F-Point Budget Guard

This is a **hard safety lock**, not a configuration option:

- **Default**: `page=1` only, zero F-points consumed
- **To unlock**: user must explicitly authorize F-point spend
- **Scope**: per-request — unlocking one query does not unlock the next

## Caching Strategy

- **Exact hash match** — query + fields + full + page + size all participate in the hash
- **Covering cache optimization** — requesting `page>1` auto-checks whether an existing `page=1` cache already covers the needed range
- **TTL**: `full=false` 24 hours, `full=true` 7 days
- **Account info**: separate cache, 5-minute TTL

## FAQ

**Q: Can free registered users use it?**
A: No. Registered users have no API access. Every search first verifies the account via the info endpoint; unpaid accounts are rejected.

**Q: Can I disable caching?**
A: `search` supports `--no-cache` to skip the cache, but it's not recommended for regular use. For fresh data, shorten TTL or manually run `cache-clean`.

**Q: Can I use it as a standalone CLI?**
A: Yes. All output is structured JSON; it works without an AI agent.

**Q: Why no query-subset cache reuse?**
A: Intentional. FOFA syntax is complex; subset matching is error-prone. Safety over cleverness — exact hash only.

**Q: What does the audit log record?**
A: Timestamp, subcommand, query, parameters, result code, duration. View with `audit-log`, purge with `audit-clean`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). PRs welcome — please keep it zero-dependency.

## License

MIT — see [LICENSE](LICENSE).
