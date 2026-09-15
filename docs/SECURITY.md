# Security Notes and Threat Model

VELES processes only open-source data, but its output (who is watching which
vessel, analyst notes, exports) is sensitive, and the platform is meant to run
unattended on a small device reachable from the internet. This document lists
what is protected, what is not, and what to do about it.

## Assets

* Analyst work product: investigation statuses, notes, exported reports.
* The audit trail (integrity matters more than confidentiality).
* Credentials in `backend/.env`: exchange keys, AIS provider keys, SMTP,
  webhook URL, API token.
* Availability of collection (a Pi running 24/7).

## Threats and mitigations

| Threat | Mitigation | Residual risk |
|--------|------------|---------------|
| Unauthenticated access to the API/UI over the tunnel | `VELES_API_TOKEN` (X-API-Key / Bearer / WebSocket `access_token`); Cloudflare Access in front of the hostname | Single shared token, no per-user identity - audit entries record what the operator typed as their name. Use Cloudflare Access with named identities for multi-user deployments. |
| Tampering with the audit log | Append-only: ORM listeners reject updates/deletes; SQLite triggers reject them at the database level | Root on the Pi can still edit the file; ship the DB (or exported JSON) off-box daily for a tamper-evident copy. |
| Credential leakage | `.env` is git-ignored; placeholders are treated as unset; keys are never returned by any endpoint | Anyone with shell access to the Pi can read `.env`. |
| Malicious or corrupted upstream data (AIS spoofing, list downloads) | Position-plausibility checks flag impossible reports instead of trusting them; truncated list downloads never mass-delist; all inputs validated by Pydantic; SQL through SQLAlchemy bind parameters only | Spoofed positions are still stored (they are the evidence) - they carry a `position_anomaly` indicator. |
| Cross-site scripting through vessel names / remarks | React escapes all rendered text; Leaflet popups are built with React, not raw HTML | None known. |
| Denial of service (exchange/AIS bursts, WebSocket fan-out) | One dedicated bot loop with `max_instances=1` per job; batched WebSocket frames; bounded query limits (`limit <= 20000`) | A malicious client could still hammer heavy endpoints - put rate limiting in Cloudflare or Nginx (`limit_req`) if exposed publicly. |
| Loss of collection | systemd `Restart=always`; `deployment/health-check.py` restarts on stale data; retention keeps the DB small | SD-card wear: put the DB on an SSD/NVMe and back it up. |

## Hardening checklist for an exposed deployment

1. Set `VELES_API_TOKEN` and paste it in Settings on each analyst browser.
2. Put the tunnel hostname behind Cloudflare Access (e-mail OTP or SSO).
3. Keep Nginx on `127.0.0.1`-bound upstreams only (default config).
4. `chmod 600 backend/.env`; don't commit it; rotate keys if the Pi is lost.
5. Set `classification.banner` to match the sensitivity of your analysis.
6. Back up `backend/veles.db` (or `POST /api/maritime/audit-log/export`)
   off-box daily; the audit log is only tamper-*evident* if a copy exists.
7. Review `docs/DATA_SOURCES.md` licensing before redistributing outputs.

## What VELES does not do

* No user accounts, roles or per-user classification levels (MVP scope).
* No encryption at rest beyond what the OS provides.
* No outbound proxies - the Pi talks directly to exchanges, AIS providers and
  the OFAC/EU/UN hosts; use an egress filter if that matters.
* Not a legal determination: matches and indicators are analytic leads.
