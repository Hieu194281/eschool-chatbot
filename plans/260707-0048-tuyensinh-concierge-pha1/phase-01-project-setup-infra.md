# Phase 01 — Project Setup & Infra

## Context Links
- Plan: [plan.md](plan.md)
- Stack ref: `plans/reports/researcher-260707-0012-langgraph-gemini-stack.md`
- Brainstorm decisions: `plans/reports/brainstorm-260707-0012-tuyensinh-concierge-pha1.md` §4

## Overview
- **Priority:** P1 (blocker for all)
- **Status:** completed
- **Effort:** ~1d
- Scaffold standalone Python service: venv, deps, config schema (pydantic-settings), Postgres via docker-compose, config module. No app logic yet — just a runnable skeleton + health check.

## Key Insights
- Chatbot is a **standalone service** with its own DB — do NOT touch existing eSchool code.
- Version caveat: install **latest stable**, verify model IDs + package versions at setup (no hard-pin of researcher-reported versions).
- Windows dev host (PowerShell) but deploy target Linux VPS — keep commands cross-platform; document both.
- Secrets ONLY in `.env` (gitignored). Config module reads env; never inline secrets.
- All config is centralized so later phases import one `settings` object (DRY).

## Requirements
**Functional**
- `python -m app.main` (or `uvicorn`) boots FastAPI, `GET /health` → 200 `{"status":"ok"}`.
- Postgres reachable via docker-compose; connection string from config.
- Config validates required secrets present at startup; fails fast with clear message if missing.

**Non-functional**
- Files <200 LOC, kebab-case module names.
- `.env.example` committed (no real secrets); `.env` gitignored.
- Reproducible install (pinned `requirements.txt` generated after verifying latest stable).

## Architecture
```
chatbot/                      # standalone service root (new)
├── app/
│   ├── main.py               # FastAPI app factory + /health + lifespan
│   ├── config/
│   │   └── settings.py       # pydantic-settings Settings (all env)
│   └── __init__.py
├── docker-compose.yml        # postgres:16 service + volume
├── .env.example
├── .env                      # gitignored
├── .gitignore
├── requirements.txt
└── README.md                 # run instructions (win + linux)
```
**Data flow:** env → `Settings` (validated singleton) → imported by every module. Postgres container exposes 5432 → `POSTGRES_DSN`.

### Config schema (settings.py — env keys)
```
# Channel (Messenger)
PAGE_ACCESS_TOKEN, APP_SECRET, VERIFY_TOKEN, MESSENGER_API_VERSION (default v21.0)
# Gemini
GOOGLE_API_KEY
GEMINI_MODEL_MAIN=gemini-2.5-flash
GEMINI_MODEL_LITE=gemini-2.5-flash-lite
GEMINI_EMBED_MODEL=gemini-embedding-001
# Google Sheet KB + leads
GOOGLE_SA_JSON_PATH        # service-account json path
KB_SHEET_ID, LEADS_SHEET_ID
KB_SYNC_INTERVAL_SEC=300
# Postgres
POSTGRES_DSN=postgresql://user:pass@localhost:5432/tuyensinh
# Telegram
TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
TELEGRAM_WEBHOOK_SECRET    # /resume webhook auth (X-Telegram-Bot-Api-Secret-Token); Ph05
# Rate limit / spend caps (Ph04)
RATE_LIMIT_PER_MIN=10
RATE_LIMIT_PER_DAY=200
MAX_CONCURRENT_INVOKES=20
GEMINI_DAILY_BUDGET        # spend/quota alert threshold (Telegram alert + canned degrade)
# PII retention (Ph05)
PII_RETENTION_DAYS=180     # purge checkpoints + lead rows past window
# App behavior
DEBOUNCE_SECONDS=6
SHADOW_MODE=true           # phase 06 toggle, default safe
HANDOFF_AUTO_RESUME_HOURS=24
LOG_LEVEL=INFO
```
Use `pydantic-settings BaseSettings` with `model_config = SettingsConfigDict(env_file=".env")`. Group nothing prematurely (KISS) — flat is fine for <25 keys.

## Related Code Files
**Create**
- `chatbot/app/config/settings.py` — Settings class + `get_settings()` cached singleton
- `chatbot/app/main.py` — FastAPI factory, `/health`, lifespan hook (placeholder for graph/KB init in later phases)
- `chatbot/app/__init__.py`
- `chatbot/docker-compose.yml`
- `chatbot/.env.example`
- `chatbot/.gitignore` (add `.env`, `*.json` sa-creds, `__pycache__`, `.venv`)
- `chatbot/requirements.txt`
- `chatbot/README.md`

**Modify** — none (root `.gitignore` already exists; add chatbot patterns if service lives at root).

## Implementation Steps
1. Decide service root dir (`chatbot/` under repo root — keeps standalone, isolated from eSchool).
2. Create venv: Windows `python -m venv .venv && .\.venv\Scripts\Activate.ps1`; Linux `python3 -m venv .venv && source .venv/bin/activate`.
3. Install deps (latest stable): `pip install fastapi uvicorn[standard] langgraph langgraph-checkpoint-postgres langchain-google-genai google-genai gspread httpx pydantic-settings apscheduler`. Then `pip freeze > requirements.txt`.
4. **Verify at setup** (write actual IDs into `.env.example` comments): confirm `gemini-2.5-flash` / `gemini-2.5-flash-lite` / `gemini-embedding-001` resolve via a 1-line probe; confirm `langgraph.checkpoint.postgres.AsyncPostgresSaver` importable.
5. Write `settings.py` with all keys above; `get_settings()` uses `@lru_cache`.
6. Write `docker-compose.yml`: `postgres:16`, env `POSTGRES_USER/PASSWORD/DB`, named volume, port 5432, healthcheck.
7. Write `main.py`: app factory, `/health`, empty lifespan (later phases attach KB sync + checkpointer).
8. Write `.env.example`, `.gitignore`, `README.md` (run steps win+linux, `docker compose up -d`).
9. Boot check: `docker compose up -d` → `uvicorn app.main:app --reload` → curl `/health`.

## Todo List
- [ ] Service root + venv created (win + linux documented)
- [ ] Deps installed latest-stable; `requirements.txt` frozen
- [ ] Model IDs + AsyncPostgresSaver import verified
- [ ] `settings.py` with validated env schema + cached singleton
- [ ] `docker-compose.yml` postgres + healthcheck
- [ ] `main.py` FastAPI + `/health` + lifespan placeholder
- [ ] `.env.example`, `.gitignore`, `README.md`
- [ ] Boot check passes (health 200, postgres reachable)

## Success Criteria
- `docker compose up -d` brings healthy Postgres.
- `uvicorn app.main:app` boots; `GET /health` → 200.
- Missing required env → startup fails with explicit error naming the key.
- No secret values committed; `.env` gitignored; `.env.example` has placeholders only.

## Risk Assessment
| Risk | L×I | Mitigation |
|---|---|---|
| Researcher versions wrong (e.g. "langgraph v3.1") | High×Low | Install latest stable, verify imports; don't pin from report |
| Model ID renamed/preview-only | Med×High | Probe at setup; keep model IDs in config, not hardcoded |
| Secret leak to git | Low×High | `.gitignore` `.env` + sa-json BEFORE first commit; commit `.env.example` only |
| Win/Linux path divergence | Med×Low | Config uses env for paths; document both shells in README |

## Security Considerations
- All secrets in `.env` (PAGE_ACCESS_TOKEN, APP_SECRET, VERIFY_TOKEN, GOOGLE_API_KEY, GOOGLE_SA_JSON_PATH, TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET, POSTGRES_DSN).
- Service-account JSON stored outside repo or path-referenced + gitignored.
- Postgres credentials only via env; no defaults in code.
- Consider `LANGGRAPH_STRICT_MSGPACK=true` env (checkpoint deserialization hardening) — set in Phase 03 wiring.

## Next Steps
- Unblocks Phase 02 (KB layer imports `settings`, gspread creds) and Phase 03 (Postgres DSN for checkpointer).
