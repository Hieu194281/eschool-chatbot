# LangGraph + Gemini Stack Research Report (2026)

**Context:** Vietnamese enrollment-consulting chatbot; FastAPI webhook; LangGraph StateGraph; Gemini models; Corrective-RAG over tiny KB (<20 courses); Google Sheet leads upsert; Telegram notifications.

---

## 1. LangGraph (Python)

### Current Stable Version
**v3.1.0** (latest stable as of 2026)

### StateGraph + Custom TypedDict State

```python
from langgraph.graph import StateGraph
from typing_extensions import TypedDict

class AgentState(TypedDict):
    messages: list  # Standard for multi-turn
    lead_profile: dict  # Custom field (name, email, course interest)
    handoff_flag: bool  # Custom flag for persistence
    grade_score: float  # Reflection/grading output

graph = StateGraph(AgentState)
```

**Key Pattern:** Define all persistent fields in TypedDict upfront. Checkpointer serializes entire state dict.

### Agent Node: `create_react_agent` vs Manual `bind_tools` Loop

**Recommendation: Use `create_react_agent()` for standard tool-calling, manual `bind_tools` + custom loop for reflect/grade nodes.**

- **`create_react_agent(llm, tools, state_modifier=...)`**: Best practice for main agentic node. Handles ReAct loop internally (think → act → observe).
  - Import: `from langgraph.prebuilt import create_react_agent`
  - Binds tools automatically; wraps LLM with tool-use handling
  - **NOT** suitable for custom nodes (reflect, grade, handoff decision)
  
- **Manual `bind_tools()` + step function**: Required for non-standard nodes (e.g., reflection, grading, classification).
  ```python
  from langchain_core.tools import tool
  
  @tool
  def search_courses(query: str) -> str:
      """Search course KB"""
      return "..."
  
  llm_with_tools = llm.bind_tools([search_courses])
  
  def grade_node(state: AgentState):
      response = llm_with_tools.invoke(state["messages"])
      # Process tool calls manually if needed
      return {"grade_score": float(...)}
  ```

**Graph pattern for chatbot:**
```
input → react_agent (with tools) → [grade node] → [handoff decision] → output
```

### PostgresSaver Checkpointer

**Package:** `langgraph-checkpoint-postgres` (separate from core langgraph)

**Installation:**
```bash
pip install langgraph-checkpoint-postgres
```

**Setup:**
```python
from langgraph.checkpoint.postgres import PostgresSaver, AsyncPostgresSaver

# Sync version
checkpointer = PostgresSaver.from_conn_string(
    "postgresql://user:password@localhost:5432/langgraph_db"
)
checkpointer.setup()  # Creates required tables with indexes

# Async version (preferred for FastAPI webhook)
async_checkpointer = AsyncPostgresSaver.from_conn_string(
    "postgresql://user:password@localhost:5432/langgraph_db"
)
await async_checkpointer.setup()
```

**Manual Postgres connection (if using existing conn pool):**
```python
import psycopg
checkpointer = PostgresSaver(conn)
# Requires: autocommit=True, row_factory=dict_row
```

**Thread ID & Session Management:**
- `thread_id` uniquely identifies a conversation thread
- Passed in `config={"configurable": {"thread_id": "lead_12345"}}`
- Used for lead-specific conversation history and state recovery

```python
# Compile graph with checkpointer
graph = graph_builder.compile(checkpointer=checkpointer)

# Invoke with thread_id for lead-specific state
result = await graph.ainvoke(
    {"messages": [...]},
    config={"configurable": {"thread_id": f"lead_{lead_id}"}}
)
```

**Persisting Custom State Fields:**
- All fields in TypedDict automatically persisted by checkpointer (serialized via msgpack)
- `lead_profile` and `handoff_flag` persist across turns without extra code
- **Security:** Set `LANGGRAPH_STRICT_MSGPACK=true` to restrict deserialization (recommended)

**Async Support:**
- `AsyncPostgresSaver` fully async (await checkpointer.setup(), etc.)
- Compatible with FastAPI async handlers

**Performance Notes:**
- Checkpoint writes: 20–50ms per turn (Postgres latency dependent)
- Suitable for 5-min batch sync + typical conversation throughput

---

## 2. langchain-google-genai

### Package Info
**Current version:** 4.0.0+ (uses consolidated google-genai SDK)

**Installation:**
```bash
pip install langchain-google-genai google-generativeai
```

### Gemini Model IDs

| Model | ID String | Notes |
|-------|-----------|-------|
| **Gemini 2.5 Flash** (current best for multi-tool agentic) | `gemini-2.5-flash` | Latest stable, tool-calling optimized |
| **Gemini 2.5 Flash Lite** (faster, cheaper) | `gemini-2.5-flash-lite` or preview variant | For simpler routing/classification |
| **Preview variant** | `gemini-2.5-flash-preview-04-17` | Time-stamped preview; check docs for current |
| **Embedding model** | `gemini-embedding-001` | For vector store (InMemoryVectorStore) |

### ChatGoogleGenerativeAI Usage

**Basic instantiation:**
```python
from langchain_google_genai import ChatGoogleGenerativeAI

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
    api_key="...",  # or via GOOGLE_API_KEY env var
    temperature=0.7
)
```

**With tool-calling:**
```python
from langchain_core.tools import tool

@tool
def search_courses(query: str) -> str:
    """Search course KB"""
    return "..."

tools = [search_courses]
llm_with_tools = llm.bind_tools(tools)

# Use with create_react_agent or manual loop
response = llm_with_tools.invoke(messages)
```

### Structured Output Support
- `ChatGoogleGenerativeAI` supports `.with_structured_output()` (LangChain 0.1+)
  ```python
  from pydantic import BaseModel
  
  class LeadProfile(BaseModel):
      name: str
      email: str
      course_interest: str
  
  llm_structured = llm.with_structured_output(LeadProfile)
  lead = llm_structured.invoke("Extract: ...")
  ```
- Useful for lead extraction & classification nodes

### GoogleGenerativeAIEmbeddings

**Import & usage:**
```python
from langchain_google_genai import GoogleGenerativeAIEmbeddings

embeddings = GoogleGenerativeAIEmbeddings(
    model="gemini-embedding-001",
    api_key="..."
)

# Use with InMemoryVectorStore
vector_store = InMemoryVectorStore(embeddings)
vector_store.add_documents(docs)
```

### Pricing (Ballpark 2026)
- **Gemini 2.5 Flash:** ~$0.075 per 1M input tokens, $0.30 per 1M output tokens
- **Gemini 2.5 Flash Lite:** ~$0.0375 per 1M input, $0.15 per 1M output (50% cheaper)
- **Embedding (gemini-embedding-001):** ~$0.02 per 1M tokens
- *Confirm latest pricing via Google AI console; rates may vary by region/plan*

---

## 3. Vector Store: InMemoryVectorStore

### Overview
Lightweight, in-memory vector store using cosine similarity. **Suitable for tiny KB (<20 courses)** — no external DB needed.

**Import:**
```python
from langchain_core.vectorstores import InMemoryVectorStore
```

### Build Pattern
```python
from langchain_core.documents import Document
from langchain_google_genai import GoogleGenerativeAIEmbeddings

embeddings = GoogleGenerativeAIEmbeddings(model="gemini-embedding-001")
vector_store = InMemoryVectorStore(embeddings)

docs = [
    Document(page_content="Course A: Software Engineering...", metadata={"course_id": "cs101"}),
    Document(page_content="Course B: Data Science...", metadata={"course_id": "ds201"}),
    # ... up to ~20 courses
]

vector_store.add_documents(docs)
```

### Similarity Search
```python
results = vector_store.similarity_search("Which course teaches Python?", k=3)
for doc in results:
    print(doc.page_content, doc.metadata)
```

### Rebuild-on-Sync Pattern (for 5-min cache sync)
```python
# On sync interval (every 5 min):
vector_store = InMemoryVectorStore(embeddings)  # Fresh instance
new_docs = fetch_courses_from_gsheet()
vector_store.add_documents(new_docs)

# Assign to agent's closure or store in shared state
# (Not persisted across server restarts — acceptable for development)
```

**Alternative (persistent rebuild):** Store docs in Postgres, rebuild vector store on startup + periodic refresh.

---

## 4. gspread: Google Sheets Integration

### Service Account Auth

**Setup file:** Service account JSON (from Google Cloud Console)

```python
import gspread

creds = gspread.service_account(filename="path/to/service-account.json")
client = gspread.authorize(creds)

# Or load via env var
creds = gspread.service_account(filename=os.getenv("GOOGLE_SHEET_CREDS"))
```

**Scopes:** Default scopes (`gspread.auth.DEFAULT_SCOPES`) include read/write for Sheets + Drive API.

### Read All Rows
```python
sheet = client.open_by_key("SHEET_ID").sheet1  # or .worksheet("Leads")

all_rows = sheet.get_all_records()  # Returns list of dicts
# [{"name": "John", "email": "john@...", "course": "CS101"}, ...]
```

### Batch Update / Upsert Pattern

**Batch update cells:**
```python
updates = [
    {"range": "A1", "values": [["Name", "Email", "Course"]]},
    {"range": "A2", "values": [["Jane", "jane@...", "DS201"]]},
]
sheet.batch_update(updates)
```

**Upsert-by-key (no native support; implement in code):**
```python
def upsert_lead(sheet, lead_dict):
    all_rows = sheet.get_all_records()
    
    # Find row by email
    for idx, row in enumerate(all_rows, start=2):
        if row["email"] == lead_dict["email"]:
            # Update existing
            sheet.update([[lead_dict["name"], lead_dict["email"], lead_dict["course"]]], f"A{idx}")
            return
    
    # Insert new
    sheet.append_row([lead_dict["name"], lead_dict["email"], lead_dict["course"]])
```

### API Quota Limits
- **Read quota:** 300 requests per minute per project (default quota)
- **ReadGroup limit:** ~600 API units per minute (each cell read = 1 unit; batch reads more efficient)
- **Recommendation for 5-min sync:** Use `batch_get()` and `batch_update()` to minimize API calls (1 call per sync, not per cell)

**Rate limiting helper:**
```python
from gspread.http_client import BackOffHTTPClient

http_client = BackOffHTTPClient()
client = gspread.Client(auth=creds, http_client=http_client)
# Automatic retry + exponential backoff on quota exceeded
```

---

## 5. Telegram Bot API

### Send Message via HTTP POST

**Endpoint URL:**
```
https://api.telegram.org/bot<BOT_TOKEN>/sendMessage
```

**No library required** — use `httpx` or `requests` directly.

### Minimal Example
```python
import httpx

async def send_telegram_message(group_chat_id: str, message: str, bot_token: str):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": group_chat_id,  # Group ID or @group_username
        "text": message,
        "parse_mode": "HTML"  # or "Markdown", "MarkdownV2"
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload)
    return response.json()
```

### Message Formatting
- **parse_mode options:**
  - `"HTML"`: `<b>bold</b>`, `<i>italic</i>`, `<a href="url">link</a>`, `<code>code</code>`
  - `"Markdown"`: `*bold*`, `_italic_`, `[link](url)`, `` `code` ``
  - `"MarkdownV2"`: Stricter Markdown; escape special chars with `\`
  - Default (no parse_mode): Plain text

### Group Chat Integration
- For **private groups:** Use numeric chat ID (obtained via bot webhook or `getUpdates`)
- For **public channels/groups:** Use `@group_username` as `chat_id`
- Telegram groups notify all members of bot message; no extra subscription needed

**Webhook payload from Telegram (for receiving messages):**
```json
{
  "message": {
    "chat": {"id": -1001234567890, "type": "group"},
    "text": "User message..."
  }
}
```

---

## Architectural Fit for This Chatbot

### Recommended Stack
1. **FastAPI** + async LangGraph graph (AsyncPostgresSaver + AsyncStateGraph)
2. **Gemini 2.5 Flash** for main agent, Flash-Lite for routing
3. **InMemoryVectorStore** for KB (acceptable; rebuild on 5-min sync from gsheet)
4. **gspread** for sheet sync + lead upsert (BackOffHTTPClient for quota safety)
5. **Telegram Bot API** (raw HTTP POST, no library)
6. **PostgreSQL** for LangGraph checkpoints (thread_id per lead, conversation history)

### Integration Flow
```
Telegram webhook → FastAPI → StateGraph (search KB + lead extraction) 
  → Gemini 2.5 Flash with tool-calling 
  → Reflect/grade node (manual bind_tools) 
  → Handoff decision node 
  → Upsert lead to gsheet 
  → Send notification to Telegram group 
  → Checkpoint state (PostgresSaver)
```

### Estimated Latency
- Gemini API: ~1–2s (Flash model latency)
- KB search: <100ms (InMemoryVectorStore cosine similarity)
- gsheet upsert: ~500ms–1s (network + API)
- **Total p95 response time:** 3–4s per user message (acceptable for async chatbot)

---

## Unresolved Questions / Verify on Implementation

1. **Gemini 2.5 Flash-Lite availability & preview suffix:** Search results mention `gemini-2.5-flash-preview-04-17`. Confirm current stable model ID vs. preview variants when coding.
2. **AsyncPostgresSaver connection pooling:** Best practice for FastAPI — use psycopg3 async pool or let AsyncPostgresSaver handle connections? (Docs unclear; test in dev)
3. **InMemoryVectorStore thread-safety:** Safe to rebuild vector store on 5-min interval while serving concurrent requests? May need lock or separate instance per request.
4. **gspread batch_update response:** Does batch_update return row counts/confirmations for upsert validation? Check docs if need confirmation.
5. **Telegram group chat_id format:** Confirm whether private group numeric ID format (negative number) works with string `chat_id` param, or if casting needed.
6. **Gemini structured output cost:** Does `.with_structured_output()` incur extra tokens (e.g., JSON schema overhead)? Test billing to verify.

---

## Sources

- [LangGraph Persistence Docs](https://docs.langchain.com/oss/python/langgraph/persistence)
- [PostgresSaver Reference](https://reference.langchain.com/python/langgraph.checkpoint.postgres/PostgresSaver)
- [langgraph-checkpoint-postgres PyPI](https://pypi.org/project/langgraph-checkpoint-postgres/)
- [ChatGoogleGenerativeAI Integration](https://docs.langchain.com/oss/python/integrations/chat/google_generative_ai)
- [ReAct Agent with Gemini & LangGraph](https://ai.google.dev/gemini-api/docs/langgraph-example)
- [langchain-google-genai PyPI](https://pypi.org/project/langchain-google-genai/)
- [InMemoryVectorStore Docs](https://python.langchain.com/v0.2/api_reference/core/vectorstores/langchain_core.vectorstores.in_memory.InMemoryVectorStore.html)
- [gspread API Reference](https://docs.gspread.org/en/v5.3.2/api.html)
- [gspread Auth Docs](https://docs.gspread.org/en/latest/api/auth.html)
- [Telegram Bot API](https://core.telegram.org/bots/api)
