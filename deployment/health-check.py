#!/usr/bin/env python3
"""External watchdog for the VELES service on the Pi.

Polls ``/api/health``; if it fails (or the bots are stale) the script restarts
the systemd unit and appends a line to the log.  Run it from cron:

    */5 * * * * /usr/bin/python3 /home/pi/veles-osint/deployment/health-check.py >> /var/log/veles-watchdog.log 2>&1

Standard library only, so it works before the venv exists.
"""

import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

URL = "http://127.0.0.1:8000/api/health"
SERVICE = "veles"
STALE_MARKET_MINUTES = 15  # candles should arrive every minute
STALE_AIS_MINUTES = 30  # positions every 30 s when a source is configured


def parse(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def main() -> int:
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    try:
        with urllib.request.urlopen(URL, timeout=10) as response:
            health = json.load(response)
    except Exception as exc:  # noqa: BLE001
        print(f"{stamp} health check failed ({exc}); restarting {SERVICE}")
        subprocess.run(["sudo", "systemctl", "restart", SERVICE], check=False)
        return 1

    problems = []
    if health.get("status") != "ok":
        problems.append(f"status={health.get('status')}")
    if not health.get("scheduler", {}).get("running"):
        problems.append("scheduler not running")
    market = parse(health.get("last_market_update"))
    if market and now - market > timedelta(minutes=STALE_MARKET_MINUTES):
        problems.append(f"market data stale ({market:%H:%M})")
    maritime = health.get("bots", {}).get("maritime", {})
    ais = parse(health.get("last_ais_update"))
    if maritime.get("sources") and ais and now - ais > timedelta(minutes=STALE_AIS_MINUTES):
        problems.append(f"AIS data stale ({ais:%H:%M})")

    if problems:
        print(f"{stamp} unhealthy: {', '.join(problems)}; restarting {SERVICE}")
        subprocess.run(["sudo", "systemctl", "restart", SERVICE], check=False)
        return 1
    if "--quiet" not in sys.argv:
        print(f"{stamp} ok - v{health.get('version')} up {health.get('uptime_seconds', 0) / 3600:.1f} h")
    return 0


if __name__ == "__main__":
    sys.exit(main())
