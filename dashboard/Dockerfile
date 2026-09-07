# Dashboard (Vite + React). Build the static app and serve it with `vite preview`
# (handles SPA routing). API base + token are baked at build time via ARGs, since
# Vite inlines VITE_* variables into the bundle.
FROM node:20-alpine

WORKDIR /app

# Install deps first for layer caching
COPY package.json package-lock.json ./
RUN npm ci

# App source
COPY . .

# Build-time config (browser talks to the backend directly, so this must be a
# URL reachable from the browser — e.g. http://localhost:8010 for local).
ARG VITE_API_BASE=http://localhost:8010
ARG VITE_CLIENT_TOKEN=
ARG VITE_CAMPAIGN=
ENV VITE_API_BASE=$VITE_API_BASE \
    VITE_CLIENT_TOKEN=$VITE_CLIENT_TOKEN \
    VITE_CAMPAIGN=$VITE_CAMPAIGN

RUN npm run build

EXPOSE 5300
CMD ["npm", "run", "preview", "--", "--host", "0.0.0.0", "--port", "5300"]
