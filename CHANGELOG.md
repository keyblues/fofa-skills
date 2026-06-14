# Changelog

## 0.1.0 — 2026-06-14

### Added
- SKILL.md metadata header with name, version, triggers, and compatibility declarations
- Skill activation conditions and boundary/refusal rules in SKILL.md
- Penetration testing workflows: cross-correlation pivoting, JARM C2 detection, deep certificate analysis, ICP filing correlation
- FOFA syntax additions: `cert.subject`, `cert.issuer`, `jarm`, `icp`, `cname`, `mf_hash`, `body_hash`, `after`, `before` examples
- Operation audit log (`audit_log` table + `audit-log` subcommand)
- FOFA API business error detection (HTTP 200 with `errmsg` field)
- FOFA host API response normalization (consistent structure with/without `--detail`)
- `stats` command supports comma-separated multi-field aggregation
- Covering cache optimization: page>1 requests reuse existing page=1 cache data when available
- `__fofa__` marker in all JSON outputs for reliable AI parsing
- New indexed cache columns: `banner`, `jarm`, `icp`, `cname`
- `scripts/__init__.py` for proper package structure
- Database migration helper (`_add_column_if_not_exists`) for schema upgrades

### Fixed
- `pyproject.toml` broken `[project.scripts]` entry point and deprecated `script-files`
- `fofa_errors.py` unused `Optional` import

## 1.0.0 — 2026-06-14

### Added
- FOFA search with hash-based SQLite cache
- F-point budget guard (default deny, explicit allow)
- Account info caching (5 min TTL)
- Rate limiting (1 req/s) with 429 retry backoff
- CLI subcommands: info, search, stats, host, cache-read, cache-delete, cache-export, cache-clean, cache-stats
- Summary-only search output (never floods context)
- Structured JSON error envelope
- Claude Code SKILL.md with full workflow instructions
