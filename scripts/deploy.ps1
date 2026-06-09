# Deploy GovernAI Agent API to App Engine with production secrets.
# Usage: .\scripts\deploy.ps1 [-ProjectId jupiter-ai-498513]

param(
    [string]$ProjectId = "jupiter-ai-498513"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Push-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$secretsFile = Join-Path $root ".env.production.yaml"
if (-not (Test-Path $secretsFile)) {
    throw "Missing $secretsFile. Copy secrets from .env (see app.yaml comments)."
}

try {
    & $python (Join-Path $root "scripts\merge_deploy_yaml.py") `
        (Join-Path $root "app.yaml") `
        $secretsFile `
        (Join-Path $root ".app.deploy.yaml")

    Write-Host "Deploying to App Engine (project: $ProjectId)..."
    gcloud app deploy (Join-Path $root ".app.deploy.yaml") --project=$ProjectId --quiet
    if ($LASTEXITCODE -ne 0) { throw "gcloud app deploy failed" }

    Write-Host "API: https://$ProjectId.uc.r.appspot.com"
}
finally {
    Remove-Item (Join-Path $root ".app.deploy.yaml") -ErrorAction SilentlyContinue
    Pop-Location
}
