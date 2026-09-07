# One-shot installer for Windows (PowerShell).
#   git clone <repo>; cd reddit_outreach; .\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "==> reddit-outreach installer"

# 1. Python check
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $py) {
  Write-Host "Python 3.10+ is required. Install from https://www.python.org/downloads/"
  exit 1
}

# 2. Virtual environment
if (-not (Test-Path ".venv")) {
  Write-Host "==> Creating virtual environment (.venv)"
  & $py.Source -m venv .venv
}
& .\.venv\Scripts\Activate.ps1

# 3. Dependencies
Write-Host "==> Installing dependencies"
python -m pip install --upgrade pip | Out-Null
pip install -e .

# Optional Supabase driver if DATABASE_URL is already set in .env
if ((Test-Path .env) -and (Select-String -Path .env -Pattern '^DATABASE_URL=' -Quiet)) {
  Write-Host "==> DATABASE_URL found — installing Postgres driver"
  pip install "psycopg[binary]" | Out-Null
}

# 4. Interactive setup wizard
Write-Host "==> Launching setup wizard"
python -m reddit_outreach.cli setup

Write-Host ""
Write-Host "Done. Next time, activate with:  .\.venv\Scripts\Activate.ps1"
Write-Host "Then run:  reddit-outreach run campaigns/example_campaign.yaml"
