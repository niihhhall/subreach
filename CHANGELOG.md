# Changelog

All notable changes to this project are recorded in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md` and this changelog.
- Issue forms, a pull request template and a CI workflow that runs the offline tests and the dashboard build.

### Changed

- Rewrote `README.md`: project background, install options, full command list, configuration, tests, status and credits.
- Corrected the test count in `CLAUDE.md` (183 tests pass).

## [0.1.0] - 2026-10

### Added

- First public release of Subreach.
- Multi-agent pipeline: discovery, qualification, triage, research, personalization and compliance, each with an LLM path and a heuristic fallback.
- Subreddit Scout, account warm-up swarm, optional DM drafting and signed webhook handoff.
- Reddit backends: Zernio, rdt, opencli and an offline mock.
- SQLite and Postgres stores with a migration command.
- FastAPI read-only API and server-rendered dashboard, plus a React dashboard.
- Docker, Render, Heroku and systemd deploy configs.

[Unreleased]: https://github.com/niihhhall/subreach/compare/8cd0a1f...HEAD
[0.1.0]: https://github.com/niihhhall/subreach/commit/8cd0a1f
