## What does this change?

<!-- Describe the change and why it is needed. -->

Closes #

## How was it tested?

- [ ] `python -m pytest -q` passes
- [ ] `npm run build` passes in `dashboard/` (if the dashboard changed)
- [ ] Tested by hand (describe below)

## Checklist

- [ ] Anything that posts, comments or messages on Reddit is still a dry-run unless `--confirm` is given
- [ ] Every agent I touched still has a heuristic fallback that works with no keys
- [ ] SQLite and Postgres stores still have the same methods (if storage changed)
- [ ] `README.md`, `.env.example` and `CHANGELOG.md` are updated (if users are affected)
- [ ] No secrets, tokens or personal data in the diff
