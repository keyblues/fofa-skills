# Changelog

## Unreleased

### Added
- **Target grouping via `--tag`**: `search --tag <target>` labels queries with an assessment target (e.g. `acme.com`); `correlate --tag` / `report --tag` / `cache-list --tag` operate on all queries in that target. This eliminates the AI's need to track individual hashes across a long workflow — if context compression wipes the hash list, `--tag` reads straight from cache with no F-point re-fetch.
- **`cache-list` subcommand**: list cached queries filtered by `--query` (substring of `query_raw`) or `--tag` (exact target). The hash-recovery primitive for `correlate`/`report` after context compression.
- **`cache-tag` subcommand**: retroactively tag (or re-tag) an already-cached query — group searches that were performed without `--tag`, no re-fetch, no F-point re-spend. Pass empty `--tag ""` to clear.
- `report` now accepts `--high-risk-ports` and `--admin-keywords` to override the default exposure-assessment lists, and `--limit` to cap `high_risk_ports`/`admin_panels` detail rows.
- `correlate` subcommand: cross-query correlation & de-duplication by key field (local, zero F-point cost)
- `report` subcommand: aggregated summary report across cached queries — port/country/server/protocol distributions, high-risk exposed ports, admin panels (local, zero F-point cost)
- Session-level F-point budget via `FOFA_FPOINTS_BUDGET` env var — spent total persists across CLI invocations (state file) so the budget depletes over a full AI session instead of resetting per process
- `audit-clean` subcommand to purge audit log entries older than N days
- `read()` in `fofa_cache.py` now supports an explicit `offset` parameter for precise slicing into covering caches
- Installation instructions (`pip install -e .`) to README and README_EN
- Split SKILL.md into `docs/playbooks.md`, `docs/command-reference.md`, `docs/fofa-syntax.md`
- 5-minute TTL cache for `host` and `stats` commands (free endpoints) via new `host_cache` table
- GitHub Actions CI workflow (`.github/workflows/ci.yml`) — multi-version Python compile + CLI smoke test
- `cache-stats` and `audit-clean` examples to `examples/sample-outputs.txt`
- Concurrency note in README and CONTRIBUTING (rate limiting is single-process)

### Changed
- `report` default high-risk port list expanded from 8 to 16 ports (now covers Telnet, MSSQL, Oracle, Memcached, SMB, Docker, Kibana, Kubernetes API) — reflects real exposure-assessment surfaces instead of a narrow DB/remote-access set
- `report` default admin-panel keywords expanded to cover Chinese + English panel and product names (phpMyAdmin, Grafana, Jenkins, Nacos, JBoss, WebLogic, Tomcat, etc.)
- `query_cache` schema gained a `tag` column (auto-migrated on first run)
- `correlate` overlap matrix diagonal now reports per-query unique count (was always 0)
- Rewrote README.md and README_EN.md as concise project overviews (removed AI command examples — those live in SKILL.md and docs/)
- SKILL.md reduced from 1054 to ~350 lines; detailed content moved to docs/ with cross-links
- Removed `cache-export` subcommand and `export_cache` function — SQLite is the single source of truth; use `cache-read` for filtered/paginated access.

### Fixed
- `README_EN.md` first line rendering glitch (extra `s'k` prefix)
- `CHANGELOG.md` duplicate `1.0.0` section merged into `0.1.0`
- `search` command now records an audit row for its implicit account info lookup
- Covering cache pagination bug: when a cached block starts at a non-zero global offset, the correct local offset is now used
- `pyproject.toml` package declaration fixed from empty `py-modules` to `packages = ["scripts"]`
- `examples/sample-outputs.txt` duplicate trailing `]}` removed
- Critical: `_rate_limit` function was accidentally deleted during F-point budget refactoring, causing `NameError` on every API request (`search`/`info`/`stats`/`host`); restored
- `correlate` overlap matrix diagonal now reports per-query unique count instead of 0; `duplicates_removed` no longer counts empty-key rows as duplicates
- `report()` empty-input return shape now includes all documented keys (was missing `by_port`/`high_risk_ports`/etc.); `per_query` now includes a placeholder for missing hashes
- `correlate`/`report` docstring field names corrected to match actual output (`query_hash`, `unique_by_key`)
- Invalid `--key` in `correlate` now returns `INVALID_PARAM` instead of `INTERNAL_ERROR`
- `cmd_search` cache-hit and covering-cache paths now include `tag` in output (was missing — only fresh-fetch path had it; broke output schema consistency)
- F-point budget now refunds the reserved cost when a `search` request fails (network error / API error) so a flaky connection doesn't deplete the budget for FOFA charges that never happened
- `--tag` no longer silently overrides `--hashes` in `correlate`/`report`; a stderr warning is emitted when both are given
- Implicit account-info lookup inside `search` now logs as `info-lookup` instead of `search`, so `audit-log --command search` returns only real search activity
- `NOT_FOUND` (4004) error code added and documented in SKILL.md error table (for `--tag` with no cached queries and unknown-hash `cache-tag`/`cache-delete`)
- Playbook 1 workflow commands now carry `--tag` (previously the checklist promised `--tag` but the workflow used `--hashes`, contradicting itself)

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
- FOFA search with hash-based SQLite cache
- F-point budget guard (default deny, explicit allow)
- Account info caching (5 min TTL)
- Rate limiting (1 req/s) with 429 retry backoff
- CLI subcommands: info, search, stats, host, cache-read, cache-delete, cache-clean, cache-stats
- Summary-only search output (never floods context)
- Structured JSON error envelope
- Claude Code SKILL.md with full workflow instructions

### Fixed
- `pyproject.toml` broken `[project.scripts]` entry point and deprecated `script-files`
- `fofa_errors.py` unused `Optional` import
