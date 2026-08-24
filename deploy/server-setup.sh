#!/usr/bin/env bash
# ============================================================================
# Nexa VPS bootstrap — run ON THE SERVER as root.
#
# From Windows you normally call this via deploy\deploy.ps1, which uploads
# the code first. Manual usage:
#   ssh root@<ip> 'bash -s' < deploy/server-setup.sh
#
# What it does (idempotent — safe to re-run):
#   1. Installs Docker + Compose plugin
#   2. Configures UFW (SSH/80/443 only)
#   3. Installs the app to /opt/nexa (expects /tmp/nexa-deploy.tar.gz when
#      invoked by deploy.ps1; skips copy step if already present)
#   4. Creates .env from the template if missing (never overwrites!)
#   5. docker compose up -d --build
# ============================================================================
set -euo pipefail

APP_DIR="/opt/nexa"
TARBALL="/tmp/nexa-deploy.tar.gz"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

[[ $EUID -eq 0 ]] || { echo "Run as root."; exit 1; }

# --- 1. Docker ---------------------------------------------------------------
if command -v docker >/dev/null 2>&1; then
  log "Docker already installed: $(docker --version)"
else
  log "Installing Docker"
  curl -fsSL https://get.docker.com | sh
  systemctl enable --now docker
fi

# --- 2. Firewall ---------------------------------------------------------------
log "Configuring firewall (SSH, HTTP, HTTPS only)"
if command -v ufw >/dev/null 2>&1; then
  ufw allow OpenSSH >/dev/null 2>&1 || true
  ufw allow 80/tcp  >/dev/null 2>&1 || true
  ufw allow 443/tcp >/dev/null 2>&1 || true
  ufw --force enable >/dev/null
else
  echo "ufw not found; skipping firewall setup"
fi

# --- 3. Application code -------------------------------------------------------
if [[ -f "$TARBALL" ]]; then
  log "Deploying code bundle to $APP_DIR"
  mkdir -p "$APP_DIR"
  tar -xzf "$TARBALL" -C "$APP_DIR"
  rm -f "$TARBALL"
elif [[ -d "$APP_DIR" ]]; then
  log "Existing deployment at $APP_DIR; keeping current code"
else
  echo "No code bundle found at $TARBALL and no existing $APP_DIR." >&2
  exit 1
fi

# --- 4. Environment ------------------------------------------------------------
cd "$APP_DIR"
if [[ -f .env ]]; then
  log ".env already exists — leaving it untouched"
else
  log "Creating .env from template — FILL IN THE SECRETS BEFORE GOING LIVE"
  cp .env.example .env
  chmod 600 .env
  echo ""
  echo "  !! Edit now:  nano $APP_DIR/.env"
  echo "  !! Required: SUPABASE_* keys, NVIDIA_API_KEY, NEXA_MODEL_ROUTES,"
  echo "  !!           NEXA_ALLOWED_ORIGINS, NEXA_ENV=production"
fi

# --- 5. Launch -------------------------------------------------------------------
log "Building and starting containers"
docker compose up -d --build

log "Status"
docker compose ps
echo ""
echo "Nexa deployed. Once DNS points at this server:"
echo "  curl https://<your-domain>/v1/health"
echo "Logs:   docker compose -f $APP_DIR/docker-compose.yml logs -f nexa"
