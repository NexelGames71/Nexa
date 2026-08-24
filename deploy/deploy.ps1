# ============================================================================
# Nexa one-shot deploy from Windows.
#
# Usage (from D:\output\Nexa):
#   powershell -File deploy\deploy.ps1 -VpsIp 203.0.113.10 [-Domain api.trynexa-ai.com] [-SkipBuild]
#
# First run: uploads code, installs Docker, boots the stack.
# Re-runs:   re-uploads code and rebuilds/restarts containers (.env preserved).
# ============================================================================
param(
    [Parameter(Mandatory = $true)] [string]$VpsIp,
    [string]$Domain = "api.trynexa-ai.com",
    [string]$SshUser = "root",
    # Comma-separated list of extra files to push after deploy (e.g. secrets)
    [string[]]$PushFiles = @(),
    [switch]$SkipUpload
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path $PSScriptRoot -Parent

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

# --- 0. Sanity checks -----------------------------------------------------------
Step "Preflight checks"
ssh -o BatchMode=yes -o ConnectTimeout=8 "$SshUser@$VpsIp" "echo ok" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Cannot SSH to $SshUser@$VpsIp. Check IP/key." }
Write-Host "SSH connection OK"

# --- 1. Pack the project (exclude local junk) -------------------------------------
$tarball = "/tmp/nexa-deploy.tar.gz"
if (-not $SkipUpload) {
    Step "Packing project"
    $stamp = Get-Date -Format "yyyyMMddHHmmss"
    $localTar = Join-Path $env:TEMP "nexa-$stamp.tar.gz"
    tar -czf $localTar `
        --exclude=.git --exclude=.venv --exclude=venv --exclude=__pycache__ `
        --exclude="*.pyc" --exclude=.pytest_cache --exclude=.ruff_cache `
        --exclude=.mypy_cache --exclude=.env --exclude="deploy/*.ps1" `
        -C $ProjectRoot .
    if ($LASTEXITCODE -ne 0) { throw "tar failed" }

    Step "Uploading code to $SshUser@$VpsIp"
    scp $localTar "${SshUser}@${VpsIp}:$tarball"
    Remove-Item $localTar
}

# --- 2. Push Caddyfile domain override --------------------------------------------
Step "Syncing deploy config (domain: $Domain)"
scp (Join-Path $PSScriptRoot "Caddyfile") "${SshUser}@${VpsIp}:/tmp/nexa-Caddyfile"

# --- 3. Run bootstrap on the server --------------------------------------------------
Step "Running server bootstrap (installs Docker, firewall, builds stack)"
$remoteScript = @"
set -e
mkdir -p /opt/nexa/deploy
cp /tmp/nexa-Caddyfile /opt/nexa/deploy/Caddyfile
rm -f /tmp/nexa-Caddyfile
sed -i "s/^api\..*/$Domain {/" /opt/nexa/deploy/Caddyfile 2>/dev/null || true
"@
$remoteScript | ssh "$SshUser@$VpsIp" "bash -s"
if ($LASTEXITCODE -ne 0) { throw "Remote prep failed" }

Get-Content (Join-Path $PSScriptRoot "server-setup.sh") -Raw |
    ssh "$SshUser@$VpsIp" "DOMAIN=$Domain bash -s"
if ($LASTEXITCODE -ne 0) { throw "Bootstrap failed" }

# --- 4. Optional extra file pushes ----------------------------------------------------
foreach ($f in $PushFiles) {
    Step "Pushing $f"
    scp $f "${SshUser}@${VpsIp}:/opt/nexa/"
}

# --- 5. Verify --------------------------------------------------------------------------
Step "Verifying health (may need ~30s for TLS certificate on first run)"
$ok = $false
foreach ($i in 1..12) {
    Start-Sleep -Seconds 5
    try {
        $health = Invoke-RestMethod "https://$Domain/v1/health" -TimeoutSec 10
        Write-Host ($health | ConvertTo-Json -Compress) -ForegroundColor Green
        $ok = $true
        break
    } catch {
        Write-Host "  attempt ${i}/12: $($_.Exception.Message)"
    }
}

if ($ok) {
    Write-Host "`nNexa is live at https://$Domain" -ForegroundColor Green
    Write-Host "Next: fill in secrets ->  ssh $SshUser@$VpsIp 'nano /opt/nexa/.env'"
    Write-Host "Then restart ->            ssh $SshUser@$VpsIp 'cd /opt/nexa && docker compose up -d'"
} else {
    Write-Host "`nHealth check not passing yet. Debug with:" -ForegroundColor Yellow
    Write-Host "  ssh $SshUser@$VpsIp"
    Write-Host "  cd /opt/nexa && docker compose logs -f caddy nexa"
}
