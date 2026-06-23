# Contributing to fofa-skills

Thanks for your interest in contributing.

## Getting Started

```bash
git clone <repo-url>
cd fofa-skills
```

No dependencies to install — the project uses only Python 3 stdlib.

## Project Principles

- **Zero pip dependencies.** All code uses only Python standard library.
- **AI-first design.** Scripts output structured JSON for machine consumption.
- **Safety by default.** F-point guard blocks paid operations unless explicitly authorized.
- **Small files.** Each module has a single responsibility.

## Concurrency Note

Rate limiting (`fofa_api._last_request_time`) is a **single-process global variable**. The CLI is designed for single-process use (one Claude Code session). If you embed these modules in a multi-process or multi-threaded application, you must add your own external rate limiting — the built-in 1 req/s throttle will not be enforced across processes.

## Pull Request Checklist

- [ ] No new pip dependencies introduced
- [ ] F-point guard is not bypassed
- [ ] JSON output format is backward-compatible
- [ ] Code has type hints
