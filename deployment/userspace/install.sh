#!/usr/bin/env bash
# VELES userspace install/upgrade on a Raspberry Pi (no sudo, no nginx).
#
# Run ON THE PI after the tarball from deployment/push-to-pi.sh has been
# extracted to ~/veles.  Creates the venv, installs requirements, writes the
# user systemd units (API on $PORT serving the built frontend, Cloudflare
# quick tunnel) and (re)starts them.  Idempotent.
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/veles}"
PORT="${PORT:-8090}"
UNIT_DIR="$HOME/.config/systemd/user"
CLOUDFLARED="${CLOUDFLARED:-$HOME/.local/bin/cloudflared}"
export XDG_RUNTIME_DIR="/run/user/$(id -u)"

echo "=== VELES userspace install -> $APP_DIR (port $PORT) ==="
mkdir -p "$APP_DIR/logs" "$UNIT_DIR"
cd "$APP_DIR/backend"

# 1. Python environment ------------------------------------------------------
if [ ! -x venv/bin/python ]; then
    python3 -m venv venv
fi
venv/bin/pip install --upgrade pip wheel >/dev/null
venv/bin/pip install -r requirements.txt

# 2. Environment file --------------------------------------------------------
if [ ! -f .env ]; then
    cp .env.example .env
fi
grep -q '^API_PORT=' .env && sed -i "s/^API_PORT=.*/API_PORT=$PORT/" .env || echo "API_PORT=$PORT" >> .env
grep -q '^ENVIRONMENT=' .env && sed -i "s/^ENVIRONMENT=.*/ENVIRONMENT=production/" .env || echo "ENVIRONMENT=production" >> .env
chmod 600 .env

# 3. User units --------------------------------------------------------------
cat > "$UNIT_DIR/veles.service" <<UNIT
[Unit]
Description=VELES OSINT Intelligence Platform (API + UI on port $PORT)
After=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR/backend
Environment=PYTHONUNBUFFERED=1
ExecStart=$APP_DIR/backend/venv/bin/python run.py
Restart=always
RestartSec=10
# a runaway process is restarted instead of taking the Pi down (cgroup v2 user slice)
MemoryMax=2200M
MemoryHigh=1900M
TimeoutStopSec=30
StandardOutput=append:$APP_DIR/logs/veles.out
StandardError=append:$APP_DIR/logs/veles.out

[Install]
WantedBy=default.target
UNIT

if [ -x "$CLOUDFLARED" ]; then
cat > "$UNIT_DIR/cloudflared-veles.service" <<UNIT
[Unit]
Description=Cloudflare quick tunnel for VELES (URL rotates on restart)
After=veles.service

[Service]
Type=simple
ExecStart=$CLOUDFLARED tunnel --no-autoupdate --url http://localhost:$PORT
Restart=always
RestartSec=15
StandardOutput=append:$APP_DIR/logs/cloudflared-veles.log
StandardError=append:$APP_DIR/logs/cloudflared-veles.log

[Install]
WantedBy=default.target
UNIT
fi

systemctl --user daemon-reload
systemctl --user enable veles.service >/dev/null
systemctl --user restart veles.service
if [ -x "$CLOUDFLARED" ]; then
    systemctl --user enable cloudflared-veles.service >/dev/null
    systemctl --user restart cloudflared-veles.service
fi

# 4. Smoke test --------------------------------------------------------------
for _ in $(seq 1 30); do
    if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
        echo "=== VELES is up on http://$(hostname -I | awk '{print $1}'):$PORT ==="
        break
    fi
    sleep 2
done
echo "logs: $APP_DIR/logs/veles.out | tunnel URL: grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' $APP_DIR/logs/cloudflared-veles.log | tail -1"
