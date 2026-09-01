# AGENTS.md — SME Cashflow Coach

Agent-readable guide for AI coding assistants working **in this folder only** (`use-cases/sme-cashflow-coach/`).

Human judges should start with **[README.md](README.md)**. For full requirements, read **[SPEC.md](SPEC.md)**.

---

## Purpose

WhatsApp-first **Agent Kernel** use case (Yaala Labs) for micro-SME shop owners in Sri Lanka. Owners log cash, stock, and customer credit in plain language; the system returns runway, trends, alerts, and one practical next action. Targets **UN SDG 8** and **SDG 9**.

---

## Yaala Labs / Agent Kernel stack

| Package extra | Used in | Role |
| --- | --- | --- |
| `agentkernel.adk` | `agent.py`, `demo.py`, `whatsapp_app.py` | Google ADK + Gemini agents |
| `agentkernel.core` | `tool.py` | `ToolContext`, session cache for active shop |
| `agentkernel.cli` | `demo.py` | Interactive CLI |
| `agentkernel.api` | `whatsapp_app.py` | `RESTAPI.run` FastAPI server |
| `agentkernel.whatsapp` | `whatsapp_app.py` | `AgentWhatsAppRequestHandler` base class |
| `agentkernel.aws` | `lambda.py` | Optional Lambda handler |

**Model:** `GEMINI_MODEL` env var, default `gemini-3.6-flash`. **Not** OpenAI / LangGraph / CrewAI.

**Dependency:** `agentkernel[cli,adk,api,whatsapp,aws]>=0.8.1` in `pyproject.toml`.

---

## Architecture (read before editing)

```text
Entry points
  desk.py          → domain.py + store.py          (no Agent Kernel, no LLM)
  demo.py          → GoogleADKModule → agents → tools
  whatsapp_app.py  → RESTAPI + CashflowWhatsAppHandler → agents → tools
  lambda.py        → agentkernel.aws.Lambda

Agents (agent.py)
  ledger_desk          → coordinator + handoffs (LlmAgent)
  cashflow_analyst     → summary, trends, affordability, dashboard
  business_advisor     → recommend_actions
  stock_credit_desk    → inventory + customer credit

Tools (tool.py)        → store.py + domain.py
Persistence            → SQLite data/shop.db (ShopStore)
Deterministic math     → domain.py ONLY (never in LLM prompts as source of truth)
```

**Rule:** Agents must call tools before stating any balance, stock qty, or credit amount. Money math lives in `domain.py` and is unit-tested.

---

## Must follow

1. All competition code stays under `use-cases/sme-cashflow-coach/`.
2. Never invent balances, transactions, stock, or credit — use `store.py` / tools / `domain.py`.
3. Keep `desk.py` working **without** `GOOGLE_API_KEY` or WhatsApp credentials.
4. Do not commit `.env`, `data/*.db`, or `.venv`.
5. Use **customer credit** terminology — not “udhar” in user-facing text or docs.
6. Currency default is **LKR** unless shop record says otherwise.
7. Match existing style: Black/isort line length **120** in this use case (`pyproject.toml`).
8. When adding features, add tests under `tests/` for `domain.py` / `store.py` behavior.

---

## Key files

| File | Role |
| --- | --- |
| `SPEC.md` | Coding-agent-readable product + technical spec |
| `README.md` | Human/judge-facing setup and run instructions |
| `config.yaml` | Agent Kernel session + WhatsApp default agent |
| `domain.py` | Balance, runway, health bands, parse_quick_log, trends, alerts, affordability, credit aging |
| `store.py` | SQLite CRUD: shops, transactions, inventory, credits, daily closes |
| `tool.py` | Agent Kernel tool functions (`TOOLS` list) |
| `agent.py` | Four Google ADK agents + `AGENTS` export |
| `desk.py` | No-LLM operational CLI |
| `demo.py` | Agent Kernel CLI entry |
| `menus.py` | WhatsApp interactive list + quick-reply payloads |
| `dedupe.py` | Inbound WhatsApp message-id deduplication |
| `whatsapp_app.py` | WhatsApp webhook, menus, fast 200 ACK + background processing |
| `lambda.py` | AWS Lambda entry (`Lambda.handler`) |
| `data/ledger.example.csv` | Sample import data for demos/tests |

---

## Agents (`agent.py`)

| Agent | Type | Responsibility |
| --- | --- | --- |
| `ledger_desk` | `LlmAgent` | Default intake: open/select shop, `parse_and_log`, till close, route specialists |
| `cashflow_analyst` | `Agent` | `get_cash_summary`, `get_trends`, `get_dashboard`, `check_affordability` |
| `business_advisor` | `Agent` | `recommend_actions` / dashboard-driven advice |
| `stock_credit_desk` | `Agent` | Stock + customer credit tools |

Handoffs: `ledger_desk` transfers to the three specialists per owner intent.

---

## Tools (`tool.py` — `TOOLS` list)

Session keys: `sme.active_shop`, `sme.owner` (via `ToolContext` non-volatile cache).

| Tool | Purpose |
| --- | --- |
| `set_owner_context` | Remember owner name |
| `open_shop` / `select_shop` / `list_shops` | Shop lifecycle |
| `parse_and_log` | Plain-language sale/expense/credit/collect lines |
| `log_sale` / `log_expense` | Structured logging |
| `list_recent_transactions` | Recent ledger rows |
| `get_cash_summary` / `get_runway` | Balance + runway + band |
| `get_trends` | Week-over-week comparison |
| `get_dashboard` | Summary + alerts + stock + credit snapshot |
| `recommend_actions` | Deterministic advice list |
| `check_affordability` | Can owner afford a purchase amount? |
| `set_stock_item` / `list_stock` | Inventory |
| `record_credit` / `collect_customer_credit` / `list_customer_credits` | Customer credit |
| `close_till` | Daily till close + variance |
| `import_ledger_csv` | CSV import |

---

## Local commands

From `use-cases/sme-cashflow-coach/`:

```powershell
uv sync --all-extras --dev

# No API keys
uv run python desk.py import data\ledger.example.csv
uv run python desk.py summary --shop "Nimal Bakery"
uv run pytest -q

# Gemini required
uv run python demo.py

# Gemini + WhatsApp Meta credentials required
uv run python whatsapp_app.py
```

---

## WhatsApp notes (`whatsapp_app.py`)

- Extends `AgentWhatsAppRequestHandler` as `CashflowWhatsAppHandler`.
- Returns HTTP 200 immediately; processes webhook in `BackgroundTasks`.
- Deduplicates inbound messages via `RecentMessageIds` (`dedupe.py`).
- Menu triggers: `menu`, `hi`, `help` → interactive list from `menus.py`.
- Required env: `GOOGLE_API_KEY`, `AK_WHATSAPP__VERIFY_TOKEN`, `AK_WHATSAPP__ACCESS_TOKEN`, `AK_WHATSAPP__APP_SECRET`, `AK_WHATSAPP__PHONE_NUMBER_ID`.

---

## Testing

- Tests: `tests/test_domain.py`, `test_store.py`, `test_menus.py`, `test_dedupe.py`.
- Run: `uv run pytest -q` (no API keys needed).
- Prefer testing deterministic logic in `domain.py` / `store.py` over mocking Gemini.

---

## Out of scope for this use case

- Banking, lending, tax filing, or regulated financial advice.
- Multi-tenant cloud hosting setup (optional `lambda.py` only scaffolded).
- Replacing SQLite with a hosted DB unless explicitly requested.
