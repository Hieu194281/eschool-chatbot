# Tuyển Sinh Concierge — Messenger Sales Chatbot (Pha 1)

Standalone Python/LangGraph **Corrective-RAG** enrollment-consulting chatbot for a
tutoring center. Answers khóa/học phí/lịch from a Google-Sheet KB (never invents
pricing), captures structured leads → Google Sheet, books trials, and hands off to
humans via Telegram. Launches in **shadow mode**.

> Standalone service — does NOT touch existing eSchool code. Own Postgres DB.

## Architecture (one line)

```
Messenger webhook → verify HMAC → ACK 200 → dedupe(mid) → debounce 5-8s
→ per-thread single-flight → LangGraph StateGraph (agent ⇄ tools, Corrective-RAG,
reflect-lite, deterministic pricing-guard) → Send API
```

- KB synced from Google Sheet every ~5 min into an in-memory vector store.
- **Golden rule:** học phí/ưu đãi live in structured columns, injected VERBATIM,
  never embedded, and enforced by a deterministic `pricing_guard` (fail-closed).
- State persisted via `AsyncPostgresSaver`, `thread_id = "{channel}:{user_id}"`.

## Prerequisites

- Python 3.11+ (3.12 recommended)
- Docker (for Postgres) — or a reachable Postgres 16
- A Google service-account JSON with access to the KB + Leads sheets
- Meta Page + App (Messenger), a Gemini API key, a Telegram bot + group

## Setup

### 1. Create venv + install deps

**Windows (PowerShell):**
```powershell
cd chatbot
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Linux/macOS:**
```bash
cd chatbot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> The plan installs **latest stable** and freezes. After install, regenerate the
> lock with `pip freeze > requirements.txt` and verify the model IDs resolve
> (`gemini-2.5-flash`, `gemini-2.5-flash-lite`, `gemini-embedding-001`) plus
> `from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver`.

### 2. Configure

```bash
cp .env.example .env      # Windows: copy .env.example .env
# edit .env — fill secrets; keep .env gitignored
```

### 3. Start Postgres

```bash
docker compose up -d
```

### 4. Boot the app (single worker — see note)

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
# health check:
curl http://localhost:8000/health      # → {"status":"ok"}
```

> **Run exactly ONE uvicorn worker.** Dedupe/debounce/rate-limit state is
> in-process; multiple workers would break idempotency. Redis is deferred (Pha 2).

## Tests

```bash
pytest
```

Failure-mode focused: pricing-guard, VN-numeral normalize, single-flight
serialization, upsert-after-middle-row-delete, Telegram secret-token rejection,
rate-limit, retention purge, shadow mode. See `tests/`.

## Docs

- [`docs/deployment-guide.md`](docs/deployment-guide.md) — VPS + TLS + Meta webhook
  registration + **App Review critical path** + eng-complete vs launch-ready.
- [`docs/runbook.md`](docs/runbook.md) — edit KB, read leads, `/resume`, flip
  `SHADOW_MODE`, rotate tokens, PII deletion/retention, backups.
- [`docs/algorithms-and-details.md`](docs/algorithms-and-details.md) — every
  algorithm/guard implemented (read this to know what to test).

## Google Sheet KB template (worksheet "Courses")

One row per khóa. Header row (exact names):

| course_id | ten_khoa | doi_tuong | muc_tieu | lo_trinh | lich_khai_giang | giao_vien | faq | chinh_sach | hoc_phi | uu_dai |
|---|---|---|---|---|---|---|---|---|---|---|

- `hoc_phi` / `uu_dai` = **STRUCTURED, verbatim** — never embedded.
- All other text columns are embedded for RAG.
- A row with `course_id` but empty `hoc_phi` is a half-edited row → skipped + alerted.
