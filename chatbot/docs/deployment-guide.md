# Deployment Guide — Tuyển Sinh Concierge (Pha 1)

Public-HTTPS webhook required (Meta mandates TLS). Single uvicorn worker (in-memory
dedupe/debounce/rate-limit). Postgres via docker-compose on the same VPS.

> **App Review is on the CRITICAL PATH — submit at the FRONT (parallel with
> Ph01–03), not after internal test.** Before Advanced Access a Messenger app can
> only message users who have a ROLE on the app/page → the shadow dry-run is
> STAFF-SIMULATED only. Real-prospect metrics require Advanced Access. "Engineering-
> complete" (≈11 eng-days) and "launch-ready" are SEPARATE milestones.

## 1. Provision VPS (Ubuntu 22.04+)

```bash
sudo apt update && sudo apt install -y docker.io docker-compose-plugin python3-venv git
sudo usermod -aG docker $USER   # re-login
```

## 2. Clone + configure

```bash
git clone <repo> && cd <repo>/chatbot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env && chmod 600 .env      # fill real secrets
```

Put the Google service-account JSON OUTSIDE the web root, set `GOOGLE_SA_JSON_PATH`
to its absolute path, `chmod 600` it. Share ONLY the KB + Leads sheets with the SA
email (least privilege).

## 3. Verify model IDs + imports (once)

```bash
python - <<'PY'
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver  # import must succeed
print("AsyncPostgresSaver OK")
PY
```
Confirm `gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemini-embedding-001` resolve
with your key; if renamed, change the IDs in `.env` (never in code). Then
`pip freeze > requirements.txt` to lock the verified versions.

## 4. Postgres

```bash
docker compose up -d          # postgres:16, bound to 127.0.0.1 only
docker compose ps             # healthy
```

## 5. Run (single worker) under systemd

`/etc/systemd/system/tuyensinh.service`:
```ini
[Unit]
Description=Tuyen Sinh Concierge
After=network.target docker.service

[Service]
WorkingDirectory=/home/USER/repo/chatbot
EnvironmentFile=/home/USER/repo/chatbot/.env
ExecStart=/home/USER/repo/chatbot/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
Restart=always
User=USER

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload && sudo systemctl enable --now tuyensinh
curl http://127.0.0.1:8000/health     # {"status":"ok"}
```
> `--workers 1` is MANDATORY: multiple workers break in-memory dedupe/debounce →
> duplicate replies. Redis is the Pha-2 upgrade for multi-worker.

## 6. TLS reverse proxy

**Option A — Caddy (auto-HTTPS):** `/etc/caddy/Caddyfile`
```
bot.yourdomain.com {
    reverse_proxy 127.0.0.1:8000
}
```
**Option B — Cloudflare Tunnel:** `cloudflared tunnel --url http://127.0.0.1:8000`
(quick start, no public IP needed).

## 7. Register Messenger webhook

Meta App → Messenger → Webhooks:
- Callback URL: `https://bot.yourdomain.com/webhook/messenger`
- Verify Token: your `VERIFY_TOKEN`
- Subscribe the **`messages`** field.
- Subscribe the Page to the app.

Meta calls `GET /webhook/messenger` with `hub.challenge` → the app echoes it iff the
token matches. `POST` events are HMAC-verified (`X-Hub-Signature-256`).

## 8. Register Telegram resume webhook (secret-token auth)

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook" \
  -d "url=https://bot.yourdomain.com/webhook/telegram" \
  -d "secret_token=<TELEGRAM_WEBHOOK_SECRET>"
```
Every resume POST must carry `X-Telegram-Bot-Api-Secret-Token` == your secret
(constant-time checked). A forged POST is rejected 403.

## 9. Milestones + go-live gate

- **Engineering-complete:** all phases coded, `pytest` green, shadow dry-run on
  staff-simulated conversations passes.
- **Launch-ready (flip `SHADOW_MODE=false`) requires ALL of:**
  1. Meta Advanced Access (`pages_messaging`) granted.
  2. Min volume of REAL post-approval prospect conversations logged (define
     threshold, e.g. ≥50 convos / ≥30 priced questions).
  3. ≥95% pricing/schedule answers correct (manual draft review).
  4. Zero invented-price / forbidden-commitment incidents.

Calendar date is gated by App Review (multi-week), NOT by the 11 eng-days.
