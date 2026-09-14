# Deployment

## Local development (Windows / macOS / Linux)

Requirements: Python 3.11+ (3.14 tested), Node 18+ (24 tested), git.

```bash
# Backend
cd backend
python -m venv venv
venv/Scripts/activate          # Windows;  source venv/bin/activate on Linux/macOS
pip install -r requirements.txt
cp .env.example .env           # optional - defaults work without keys
python run.py                  # http://localhost:8000  (/docs for Swagger)

# Frontend (separate terminal)
cd frontend
npm install
npm run dev                    # http://localhost:5173, /api proxied to :8000
```

`uv` users: `uv venv venv && uv pip install --python venv/Scripts/python.exe -r requirements.txt`.

Tests: `cd backend && venv/Scripts/python -m pytest`.

Single-process option: `npm run build` once, then `python run.py` serves the
built UI at `http://localhost:8000` (no Vite needed).

## Raspberry Pi 5 (production)

Tested target: Raspberry Pi OS 64-bit (Bookworm = Python 3.11, Trixie = 3.13).

```bash
sudo apt-get install -y git
git clone https://github.com/alexander-analysis/OSINT-bots.git ~/veles-osint
cd ~/veles-osint
bash deployment/pi-setup.sh
```

The script installs packages, builds the venv and frontend, copies the build to
`/var/www/veles/frontend/dist`, installs the Nginx site and the `veles`
systemd unit (substituting your user and repo path), and health-checks
`http://localhost/api/health`.

Then add API keys to `backend/.env` and restart:

```bash
nano backend/.env
sudo systemctl restart veles
```

### Operating

| Task | Command |
|------|---------|
| Status / logs | `sudo systemctl status veles` / `sudo journalctl -u veles -f` |
| Bot log files | `tail -f backend/logs/veles.log` (errors: `backend/logs/errors.log`) |
| Redeploy after `git pull` | `bash deployment/pi-setup.sh` (idempotent) |
| Inspect DB | `sqlite3 backend/veles.db ".tables"` |
| Apply migrations manually | `cd backend && venv/bin/alembic upgrade head` (also runs automatically at startup) |
| Health | `curl http://localhost/api/health` |

### Remote access

See [`deployment/cloudflare-tunnel.md`](../deployment/cloudflare-tunnel.md).

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `ModuleNotFoundError` | The venv is not active / not installed: `venv/bin/pip install -r requirements.txt` |
| `database is locked` | WAL mode is on; make sure only one `run.py` process is running (`systemctl` + a manual run is the usual cause) |
| Blank page via Nginx | Frontend not built/copied - re-run `pi-setup.sh`; check `sudo nginx -t` |
| `/api/health` returns 503 | Database path unwritable - check `DATABASE_URL` in `.env` and directory permissions |
| Node too old on Pi | `pi-setup.sh` installs NodeSource 22.x when `node < 18` |
