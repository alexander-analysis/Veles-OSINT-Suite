# Cloudflare Tunnel Setup

Exposes VELES from the Pi without opening router ports. Cloudflare terminates
HTTPS; Nginx on the Pi keeps serving plain HTTP on port 80.

## 1. Install `cloudflared` (arm64)

```bash
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb
sudo dpkg -i cloudflared.deb
cloudflared --version
```

## Option A - quick tunnel (no account, URL changes on every restart)

Good for a first look or a demo:

```bash
cloudflared tunnel --url http://localhost:80
```

The command prints a `https://<random>.trycloudflare.com` URL. It is only
valid while the command runs.

## Option B - named tunnel (stable hostname, runs as a service)

Requires a Cloudflare account with a domain.

```bash
cloudflared login                          # opens a browser to authorise
cloudflared tunnel create veles            # prints the tunnel UUID
cloudflared tunnel route dns veles veles.yourdomain.com
```

Create `~/.cloudflared/config.yml`:

```yaml
tunnel: <TUNNEL-UUID>
credentials-file: /home/pi/.cloudflared/<TUNNEL-UUID>.json

ingress:
  - hostname: veles.yourdomain.com
    service: http://localhost:80
  - service: http_status:404
```

Test it, then install as a service so it survives reboots:

```bash
cloudflared tunnel run veles               # Ctrl-C when you have confirmed it works
sudo cloudflared service install
sudo systemctl enable --now cloudflared
sudo systemctl status cloudflared
```

VELES is then available at `https://veles.yourdomain.com`.

## Access control (recommended)

The MVP has no application-level authentication. Put the hostname behind
**Cloudflare Zero Trust -> Access -> Applications** and add a policy (e-mail
OTP, Google/GitHub login, or an allow-list) so only analysts can reach it.

## Troubleshooting

| Symptom | Check |
|---------|-------|
| 502 from Cloudflare | `sudo systemctl status nginx veles` - is Nginx listening on 80? |
| Tunnel connects, page blank | Was the frontend built and copied to `/var/www/veles/frontend/dist`? Re-run `deployment/pi-setup.sh` |
| WebSocket stream fails | Ensure `service: http://localhost:80` (Nginx) not `:8000`, so the `/api/maritime/stream` upgrade block applies |
