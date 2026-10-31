# Contributing to Subreach

Thank you for helping. Bug reports, ideas, docs fixes and code are all welcome.

## Before you start

- Read the [Code of Conduct](CODE_OF_CONDUCT.md).
- Search [existing issues](https://github.com/niihhhall/subreach/issues) before you open a new one.
- For a large change, open an issue first so we can agree on the approach.
- Never report a security problem in a public issue. Use [`SECURITY.md`](SECURITY.md).

## Set up a development environment

You need Python 3.12 and Node.js 20 or newer.

```bash
git clone https://github.com/niihhhall/subreach.git
cd subreach
python -m venv .venv
source .venv/bin/activate            # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt pytest httpx2
```

For the dashboard:

```bash
cd dashboard
npm ci
npm run dev
```

No Reddit or LLM keys are needed. Set `REDDIT_BACKEND=mock` and the agents use the offline mock backend and heuristic fallbacks.

## Project rules

- **The campaign YAML is the mold.** New outreach behaviour that is specific to one offer belongs in a campaign file, not in a code fork.
- **Every agent keeps two paths:** an LLM path and a deterministic heuristic fallback. The pipeline must run end to end with no keys.
- **Loops stay safe to run unattended:** bounded per cycle, incremental saves, crash-resilient, rate-limit-aware and idempotent (dedup by post id).
- **Sending stays opt-in.** Anything that posts, comments or messages on Reddit must default to a dry-run and need `--confirm`.
- **SQLite and Postgres stores keep the same interface.** If you add a method to one, add it to the other.
- Read [`CLAUDE.md`](CLAUDE.md) for the architecture and the known gotchas.

## Run the checks

```bash
python -m pytest -q                  # offline backend tests
cd dashboard && npm run build        # dashboard type check and build
```

Add or update tests for any behaviour you change. Unset real LLM keys (for example `OPENAI_API_KEY`) in your shell before you run the tests.

## Open a pull request

1. Fork the repo and create a branch from `main`, for example `fix/zernio-retry` or `feat/threads-page`.
2. Keep each pull request small and focused on one change.
3. Write clear commit messages that say what changed and why.
4. Make sure the tests and the dashboard build pass.
5. Fill in the pull request template, link the issue, and note any new environment variables.
6. Update `README.md`, `.env.example` and `CHANGELOG.md` (under "Unreleased") when your change affects users.

GitHub Actions runs the same checks on every pull request. An automated reviewer may also leave comments; please answer or fix each one.

## License

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
