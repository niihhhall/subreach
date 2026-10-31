# Security policy

## Supported versions

Subreach is in early development. Only the latest code on the `main` branch receives security fixes.

| Version | Supported |
|---|---|
| `main` | ✅ |
| Older commits | ❌ |

## Report a vulnerability

Do not open a public issue, discussion or pull request for a security problem.

Report it privately through [GitHub private vulnerability reporting](https://github.com/niihhhall/subreach/security/advisories/new). Please include:

- what the problem is and which files or endpoints it affects,
- the steps to reproduce it,
- the impact you expect (for example, token exposure or an unwanted Reddit post),
- a suggested fix, if you have one.

You can expect a first reply within 7 days. We will keep you updated while we work on a fix, and we will credit you in the advisory unless you ask us not to.

## Scope

In scope:

- the Python package in `reddit_outreach/`, including the web dashboard and the `/api/*` endpoints,
- the React dashboard in `dashboard/`,
- the deploy configs in this repo (`Dockerfile`, `docker-compose*.yml`, `render.yaml`, `app.json`, `deploy/`).

Out of scope:

- problems in third-party services such as Reddit, Zernio or LLM providers (report those to the vendor),
- the local demo stack in `docker-compose.local.yml`, which uses the public `devtoken` token and open CORS on purpose,
- account bans that result from using the tool against a subreddit's rules.

## Keep your own deployment safe

- Use long random values for `DASHBOARD_TOKEN` and `CLIENT_TOKEN`, and use different values for each.
- `VITE_CLIENT_TOKEN` ends up in the public dashboard bundle. Never set it to your `DASHBOARD_TOKEN`.
- Set `CORS_ORIGINS` to your dashboard's address in production.
- Keep `.env` and `accounts.yaml` out of Git. Both are in `.gitignore`.
- Leave `watch --auto-comment` off unless you accept posts without human review.
