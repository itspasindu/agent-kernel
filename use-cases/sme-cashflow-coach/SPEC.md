# SPEC.md — SME Cashflow Coach

Coding-agent-readable specification for implementing and extending this use case.  
Human/judge instructions: **[README.md](README.md)**. Agent conventions: **[AGENTS.md](AGENTS.md)**.

---

## 1. Agent description

**Name:** SME Cashflow Coach  
**Competition:** IDEALIZE 2026 · Agent Kernel use case  
**Maintainer stack:** [Agent Kernel](https://kernel.yaala.ai/) by **Yaala Labs**  
**Framework adapter:** Google ADK + Gemini (`agentkernel.adk`)  
**Primary channel:** WhatsApp (Meta Cloud API)  
**SDGs:** 8 (Decent Work & Economic Growth), 9 (Industry, Innovation & Infrastructure)

A multi-agent assistant for **micro and small shop owners** (bakeries, groceries, tea kiosks). Owners message in plain language; the system maintains a persistent ledger, inventory, and customer-credit records, then returns cash runway, trends, alerts, and practical next actions.

---

## 2. Problem statement

Informal SMEs often track cash mentally or on paper. Without daily till close, stock tracking, and customer-credit follow-up, owners discover cash shortfalls and stock-outs too late. Full accounting software is too heavy for WhatsApp-native micro businesses.

---

## 3. Solution summary

| Layer | Implementation |
| --- | --- |
| Owner UX | WhatsApp menus + free text; optional CLIs |
| Agent runtime | Yaala Labs Agent Kernel + Google ADK (4 agents) |
| Business logic | Deterministic Python in `domain.py` |
| Persistence | SQLite `data/shop.db` via `ShopStore` in `store.py` |
| Tool bridge | `tool.py` exposes store/domain to agents |

---

## 4. Functional requirements

### 4.1 Cash ledger

- Log **sales** and **expenses** with amount, category, note, optional day.
- Compute **balance** from all transactions.
- Compute **runway_days** from balance and recent net daily flow.
- Assign health **band**: `HEALTHY`, `TIGHT`, or `CRITICAL` (deterministic rules in `domain.py`).
- Support **plain-language** input via `parse_quick_log` / `parse_and_log` tool, e.g.:
  - `sold 12 buns 2400`
  - `bought flour 1800`
  - `credit Amara 500 bread`
  - `paid Amara 200`

### 4.2 Customer credit

- Record credit extended to customers (`record_credit`).
- Record collections (`collect_customer_credit`).
- List open credits with **aging** buckets (deterministic in `domain.py`).
- User-facing term: **customer credit** (not “udhar”).

### 4.3 Inventory

- Track SKU quantity, unit, reorder level per shop.
- Flag **low stock** when quantity ≤ reorder level.
- Decrement/increment stock on linked sale/expense when SKU provided.

### 4.4 Daily till close

- Owner submits physical till count.
- System compares to ledger balance and stores **variance**.
- Till mismatch generates an alert on dashboard.

### 4.5 Analytics

- **Week-over-week trends:** sales, expenses, net (this week vs last week).
- **Affordability check:** given a purchase amount, say if affordable without breaking runway rules.
- **Alert dashboard:** critical cash, low stock, overdue credit, till mismatch.
- **Recommend actions:** up to three practical steps from dashboard state.

### 4.6 Agents (Google ADK)

| Agent | Must do |
| --- | --- |
| `ledger_desk` | Open/select shop, parse logs, till close, route to specialists |
| `cashflow_analyst` | Call summary/trends/dashboard/affordability tools before stating numbers |
| `business_advisor` | Call `recommend_actions` or dashboard before advice |
| `stock_credit_desk` | Stock + credit tools only; never invent outstanding balances |

**Global agent rules:**

- Always use tools before stating balances or counts.
- Replies short enough for WhatsApp.
- Default currency LKR.
- Disclaimer: not a bank, accountant, or lender.

### 4.7 WhatsApp UX

- Webhook at `/whatsapp/webhook` via Agent Kernel `RESTAPI`.
- Interactive **list menu** for common actions (`menus.py`).
- **Quick-reply buttons** after menu-driven replies.
- Menu triggers: `menu`, `hi`, `help` (case-insensitive).
- Fast HTTP 200 acknowledgment; process message in background.
- Deduplicate retried Meta message IDs.

### 4.8 Entry points

| Entry | LLM | WhatsApp | Purpose |
| --- | --- | --- | --- |
| `desk.py` | No | No | Operational CLI; judge quick start |
| `demo.py` | Gemini | No | Agent Kernel interactive CLI |
| `whatsapp_app.py` | Gemini | Yes | Production-style owner channel |
| `lambda.py` | Gemini | Optional | AWS Lambda handler scaffold |

### 4.9 Session behavior

- One **active shop** per session (cached in Agent Kernel session store).
- Owner name cached when provided.
- Config: `config.yaml` — in-memory session, default WhatsApp agent `ledger_desk`.

---

## 5. Non-functional requirements

- **Determinism:** All money, runway, band, alert, and advice logic must be reproducible from `domain.py` + `store.py` without LLM.
- **Testability:** `desk.py` and `pytest` must run without API keys.
- **Privacy:** Do not commit `data/shop.db` or `.env`.
- **Python:** 3.12+
- **Package manager:** `uv`
- **Dependency:** `agentkernel[cli,adk,api,whatsapp,aws]>=0.8.1`

---

## 6. Data model (SQLite)

Implemented in `store.py` (`ShopStore`):

| Entity | Key fields |
| --- | --- |
| Shop | id, name, owner_name, category, currency, created_at |
| Transaction | kind (sale/expense/owner_draw), amount, category, note, day, optional sku/qty |
| Inventory | sku, quantity, unit, reorder_level |
| Customer credit | customer name, amount, note, day, collected flag |
| Daily close | day, till_count, ledger_balance, variance, note |

Database path: `data/shop.db` (override via `SHOP_DB` env optional).

---

## 7. Tool contract (`tool.py`)

All tools return **JSON strings**. Agents bind via `GoogleADKToolBuilder.bind(TOOLS)`.

Active shop resolution order:

1. Explicit `shop_query` argument
2. Session cache `sme.active_shop`
3. Single shop in database
4. Else error: call `open_shop` or `select_shop`

Full tool list: see `TOOLS` at bottom of `tool.py` or **AGENTS.md**.

---

## 8. Configuration

### `config.yaml`

```yaml
session:
  type: in_memory
whatsapp:
  agent_acknowledgement: ""
  agent: ledger_desk
```

### Environment (`.env.example`)

| Variable | Required for |
| --- | --- |
| `GOOGLE_API_KEY` | `demo.py`, `whatsapp_app.py` |
| `GOOGLE_GENAI_USE_VERTEXAI=FALSE` | Gemini API (not Vertex) |
| `GEMINI_MODEL` | Model name (default `gemini-3.6-flash`) |
| `AK_WHATSAPP__*` | WhatsApp webhook only |

---

## 9. Acceptance criteria

A change is complete when:

1. `uv run pytest -q` passes (currently 19 tests).
2. `uv run python desk.py import data/ledger.example.csv` then `summary --shop "Nimal Bakery"` returns valid JSON with balance and band.
3. Agents in `demo.py` / `whatsapp_app.py` call tools — no hard-coded balances in agent instructions.
4. `desk.py` still runs without Gemini or WhatsApp env vars.
5. README.md retains all four submission sections (problem, solution, setup, run).
6. User-facing copy uses **customer credit**, not “udhar”.

---

## 10. Deployment notes

- **Local demo:** `whatsapp_app.py` + ngrok HTTPS tunnel → Meta webhook.
- **AWS:** `lambda.py` exports `handler = Lambda.handler` (requires Agent Kernel AWS deploy setup).
- **Judges:** No cloud required — use `desk.py` + `pytest`.

---

## 11. Out of scope

- Loan origination, credit scoring, or regulated financial products.
- Multi-shop enterprise dashboards.
- Tax filing or statutory accounting compliance.
- Hosted database migration (unless explicitly requested).

---

## 12. Disclaimer (must appear in README)

This coach helps owners see cash and take simple operating decisions. It is **not** banking, accounting, tax, or lending advice.
