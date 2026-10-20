# Verifies a fresh clone can be set up from the README. Local only; no deployment.
param([Parameter(Mandatory=$true)][string]$RepoUrl)
$ErrorActionPreference = "Stop"
$dir = Join-Path $env:TEMP ("changeradar_check_" + [guid]::NewGuid().ToString("N").Substring(0,8))
git clone $RepoUrl $dir
Set-Location $dir
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pytest -q
Set-Location frontend
npm install
npm run build
Write-Host "Fresh clone check passed in $dir" -ForegroundColor Green
