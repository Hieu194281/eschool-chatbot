# Tuyển Sinh Concierge

A multi-channel sales agent for tutoring centres, built on **LangGraph** and **Gemini**.
It consults prospective parents over Messenger and Telegram, captures structured leads,
books trial lessons, and hands the conversation to a human when it should not answer
alone.

The interesting part is not that an LLM answers questions. It is that this one **quotes
prices to customers**, which means a wrong answer costs real money — so the whole design
is built around not trusting the model with that.

---

## The problem this solves

A tutoring centre's Facebook page gets enrolment questions all day: which course, how
much, what schedule, is there a discount. Answering them is slow and repetitive, but
getting one wrong — quoting a price that does not exist, promising a discount nobody
approved — is worse than not answering at all.

So the agent has two jobs that pull against each other:

- **Be useful:** answer from the centre's real catalogue, capture the lead, book the trial.
- **Never be wrong about money:** and prove it, not hope for it.

Everything below follows from that tension.

---

## Architecture

```
Messenger webhook
  → verify HMAC signature
  → ACK 200 immediately
  → dedupe by message id
  → debounce 5-8s (people send three messages in a row)
  → per-thread single-flight
  → LangGraph StateGraph
  → Send API
```

The graph itself:

```
START → detect_objection
detect  ─ none ─────────────────→ agent
        ─ objection ────────────→ handle_objection
        ─ comparison / repeat ──→ fallback  (handoff, no generated reply)

agent   ─ tool_calls ───────────→ tool_exec   (loop cap → fallback)
        ─ final text ───────────→ reflect_lite

tool_exec ─ retrieved ──────────→ grade_chunks
          ─ else ───────────────→ agent

grade   ─ sufficient ───────────→ agent
        ─ insufficient ─────────→ fallback

reflect ─ ok ───────────────────→ pricing_guard
        ─ fix ──────────────────→ agent / handle_objection (once)

pricing_guard ──────────────────→ END          ← deterministic, always last
```

**Every branch converges on `reflect_lite` → `pricing_guard`.** The objection branch gets
no shortcut, precisely because it is the branch most likely to talk about money.

---

## Design decisions worth explaining

### The pricing guard is deterministic, and it runs last

The system prompt tells the model to quote prices verbatim from the catalogue. Reflection
double-checks the draft. **Neither is the guarantee.** Both are advisory.

The guarantee is `pricing_guard`: a pure, deterministic function that runs after everything
else, reads the *whole* course catalogue as a dict walk (0 tokens), binds the draft to the
course it is talking about, and checks every money, schedule and concession claim against
that course's actual facts. Any violation replaces the draft with an honest fallback and
hands off to a human.

It is **fail-closed**: if the draft states money and the guard cannot bind it to a specific
course, it blocks. An earlier version had a "single retrieved candidate" fallback for that
case; it was removed, because with the full catalogue in scope it could never fire
correctly, and a branch that silently never fires is worse than an explicit block.

*Why not just trust the model?* Because "usually correct" is not a property you can ship
when the failure mode is quoting a price that does not exist to a paying customer.

### Corrective RAG instead of plain retrieval

`agent → tool_exec → grade_chunks → agent` is a loop, not a line. A grading node (a small,
fast model) classifies whether the retrieved context is actually sufficient to answer the
question. Insufficient context routes to an honest fallback — *"let me connect you with a
consultant"* — rather than letting the main model improvise around thin retrieval.

A loop cap stops the agent from grinding: after N rounds it escalates to a human instead of
retrying forever.

### Handoff ownership is TOCTOU-safe

When the agent hands a thread to a human, it writes a row claiming that thread. If that
write fails, the agent does **not** claim the handoff succeeded.

The reason is that `sales_stage = HANDOFF` is an **absorbing state**. A transient database
blip that was reported as success would park the conversation permanently in "a human took
over" while the bot keeps answering and no human is actually watching. Degrading to a
normal turn is the safer failure: the next turn retries.

The state also distinguishes `handoff` (advisory — set by fallback, guard and reflect) from
`escalated` (this specific invocation wrote the handoff row). Without that distinction, one
routine honest-fallback would make every later turn look escalated, and a human taking over
mid-invocation would get talked over.

### Knowledge base lives in a Google Sheet

The centre's staff maintain courses, prices and schedules in a spreadsheet they already
use. It syncs into an in-memory vector store every ~5 minutes.

Prices are **never embedded**. They live in structured columns and are injected verbatim.
Embedding a price means retrieving something *similar to* a price, which is exactly the
failure this system is built to prevent.

### Why not a "deep agent"?

Long-horizon autonomous agents — plan, spawn sub-agents, work a todo list — are a good fit
for open-ended research and coding tasks. This is not one of those.

A sales conversation is short-horizon and high-consequence. What it needs is a fixed graph
with explicit edges and a gate the model cannot route around. Giving this agent the freedom
to plan its own path would remove the one property that makes it safe to point at real
customers.

---

## Stack

| Layer | Choice |
|---|---|
| Orchestration | LangGraph (`StateGraph`, conditional edges, `ToolNode`) |
| Model | Google Gemini (main + a lighter model for grading) |
| Memory | `AsyncPostgresSaver` checkpointer, `thread_id = "{channel}:{user_id}"` |
| Retrieval | In-memory vector store, synced from Google Sheets |
| Tools | `capture_lead`, `book_trial`, `handoff_to_human` — all write real state |
| Channels | Facebook Messenger, Telegram |
| Storage | Google Sheets (leads, trials), PostgreSQL (checkpoints, handoff) |
| Alerts | Telegram (hot leads, handoff requests) |

---

## Privacy

Consent is recorded at the moment a phone number is captured, with a timestamp. Phone
numbers never reach the metrics log — only their presence as a boolean. This is a
Vietnamese PDPD requirement and it is enforced in code, not in a policy document.

---

## Status

Feature-complete and running locally. **Shadow mode** is implemented for rollout: the agent
reads live traffic and composes replies without sending them, so the centre can read the
log and decide before anything reaches a customer.

Currently seeking its first deployment.

---

## Repository layout

```
chatbot/app/graph/       StateGraph, nodes, tools, prompts
chatbot/app/channel/     Messenger + Telegram adapters, dedupe, debounce, rate limit
chatbot/app/integrations/ Google Sheets, Telegram notify
chatbot/app/db/          connection pool, handoff table, retention purge
chatbot/README.md        setup and configuration
docs/                    architecture, research notes, engineering journals
plans/                   phased implementation plans, red-team and code-review reports
```

`plans/reports/` contains the red-team pass and code reviews this project was built
through. They are kept in the repository on purpose — the reasoning is part of the work.
