#!/usr/bin/env bash
# One-shot installer for macOS / Linux.
#   git clone <repo> && cd reddit_outreach && bash setup.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "==> reddit-outreach installer"

# 1. Python check
if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.10+ is required. Install it from https://www.python.org/downloads/"
  exit 1
fi

# 2. Virtual environment
if [ ! -d ".venv" ]; then
  echo "==> Creating virtual environment (.venv)"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# 3. Dependencies
echo "==> Installing dependencies"
python -m pip install --upgrade pip >/dev/null
pip install -e .

# Optional Supabase driver if the user already put a DATABASE_URL in .env
if [ -f .env ] && grep -q '^DATABASE_URL=' .env; then
  echo "==> DATABASE_URL found — installing Postgres driver"
  pip install "psycopg[binary]" >/dev/null
fi

# 4. Interactive setup wizard
echo "==> Launching setup wizard"
python -m reddit_outreach.cli setup

echo ""
echo "Done. Next time, activate the environment with:  source .venv/bin/activate"
echo "Then run:  reddit-outreach run campaigns/example_campaign.yaml"
