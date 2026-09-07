# Dashboard

The web dashboard for the Reddit Outreach system — a **read-only** view of the
pipeline (Vite + React + TypeScript + Tailwind). It reads the backend's
`/api/*` endpoints; it never writes.

## Run

```bash
npm install
npm run dev -- --port 5300      # http://localhost:5300
```

It defaults to the backend at `http://localhost:8010`. To point elsewhere, copy
`.env.example` → `.env` and set:

```
VITE_API_BASE=https://your-backend-url
VITE_CLIENT_TOKEN=your-client-token
VITE_CAMPAIGN=markeye-reddit
```

## Build / preview

```bash
npm run build       # → dist/
npm run preview     # serve the production build
```

## Docker

Built and served as part of the root `docker-compose.local.yml`. To build alone:

```bash
docker build -t outreach-dashboard \
  --build-arg VITE_API_BASE=http://localhost:8010 \
  --build-arg VITE_CLIENT_TOKEN=devtoken \
  --build-arg VITE_CAMPAIGN=markeye-reddit .
```

## Structure

- `src/lib/api.ts` — read-only API client + config
- `src/lib/adapters.ts` — maps backend shapes → UI types
- `src/hooks/` — data hooks (`useApi`, `useLeads`, `useQueue`, …)
- `src/pages/` — Overview, Leads, Review, Handoffs, Accounts, Scout, Performance
- `src/components/` — cards, tables, detail views, layout
