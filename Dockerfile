# 24/7 Reddit outreach worker.
# Build:  docker build -t reddit-outreach .
# Run:    docker run -d --name outreach --env-file .env -v ${PWD}/data:/app/data \
#           --restart unless-stopped reddit-outreach
FROM python:3.12-slim

WORKDIR /app

# Install deps first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code + campaigns
COPY reddit_outreach ./reddit_outreach
COPY campaigns ./campaigns

# Persistent lead state lives here — mount a volume so it survives restarts
VOLUME ["/app/data"]
ENV OUTREACH_DATA_DIR=/app/data
ENV PYTHONUNBUFFERED=1

# Campaign + role are env-driven so ONE image serves any campaign and either
# loop. Defaults to the watch loop on the markeye campaign; docker-compose runs
# a second container for the scout loop. Override CAMPAIGN / INTERVAL as needed.
ENV CAMPAIGN=campaigns/markeye.yaml
ENV INTERVAL=1800
CMD ["sh", "-c", "python -m reddit_outreach.cli watch \"$CAMPAIGN\" --interval \"$INTERVAL\" --draft-budget 10"]
