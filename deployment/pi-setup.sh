#!/usr/bin/env bash
# VELES Raspberry Pi 5 setup.
#
# Run from anywhere inside the cloned repository:
#     bash deployment/pi-setup.sh
#
# Installs system packages, creates the backend venv, builds the frontend,
# configures Nginx and installs/starts the systemd service.  Safe to re-run
# (it is how you redeploy after `git pull`).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="${SUDO_USER:-$USER}"
WEB_ROOT=/var/www/veles/frontend/dist

echo "=== VELES Pi 5 Setup ==="
echo "Repository:   $REPO_DIR"
echo "Service user: $RUN_USER"

# 1. System packages -------------------------------------------------------
sudo apt-get update
sudo apt-get install -y python3 python3-venv python3-dev build-essential git curl rsync \
    nginx sqlite3 libsqlite3-dev libgeos-dev libproj-dev

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    echo "ERROR: Python >= 3.11 required (found $(python3 --version))." >&2
    exit 1
fi

# 2. Node.js >= 18 (NodeSource 22.x LTS if missing or too old) -------------
if ! command -v node >/dev/null 2>&1 || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 18 ]; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
    sudo apt-get install -y nodejs
fi

# 3. Backend ---------------------------------------------------------------
cd "$REPO_DIR/backend"
[ -d venv ] || python3 -m venv venv
venv/bin/pip install --upgrade pip setuptools wheel
venv/bin/pip install -r requirements.txt
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Created backend/.env from template - add your API keys there."
fi

# 4. Frontend build -> /var/www (home directories are not readable by nginx)
cd "$REPO_DIR/frontend"
if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; else npm install --no-audit --no-fund; fi
npm run build
sudo mkdir -p "$WEB_ROOT"
sudo rsync -a --delete dist/ "$WEB_ROOT/"

# 5. Nginx -----------------------------------------------------------------
sudo cp "$REPO_DIR/deployment/nginx.conf" /etc/nginx/sites-available/veles
sudo ln -sf /etc/nginx/sites-available/veles /etc/nginx/sites-enabled/veles
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl restart nginx

# 6. systemd service (template uses pi:/home/pi/veles-osint - substitute) ---
sed -e "s|^User=.*|User=$RUN_USER|" \
    -e "s|/home/pi/veles-osint|$REPO_DIR|g" \
    "$REPO_DIR/deployment/systemd/veles.service" | sudo tee /etc/systemd/system/veles.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable veles
sudo systemctl restart veles

# 7. Smoke test ------------------------------------------------------------
sleep 4
if curl -fsS http://localhost/api/health >/dev/null; then
    echo "=== Setup complete: VELES is running at http://$(hostname -I | awk '{print $1}') ==="
else
    echo "WARNING: health check failed. Inspect with: sudo journalctl -u veles -n 50" >&2
fi
echo "Logs: sudo journalctl -u veles -f   |   backend/logs/veles.log"
