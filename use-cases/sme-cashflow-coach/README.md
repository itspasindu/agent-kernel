# SME Cashflow Coach

**IDEALIZE 2026 submission** · built with **[Agent Kernel](https://kernel.yaala.ai/) by [Yaala Labs](https://github.com/yaalalabs)**  
UN **SDG 8 — Decent Work & Economic Growth** · **SDG 9 — Industry, Innovation & Infrastructure**

WhatsApp-first coach for micro and small shop owners. Owners log sales and expenses in plain language, track **stock** and **customer credit**, run a **daily till close**, see **runway / trends / alerts**, and get one practical next action.

Do not commit `data/shop.db` or `.env` — they may hold real business figures or secrets.

---

## Documentation

This submission includes three docs — pick the one that matches your audience:

| File | Audience | Purpose |
| --- | --- | --- |
| **[README.md](README.md)** | Judges & humans | Problem statement, solution overview, setup, and how to run |
| **[SPEC.md](SPEC.md)** | Coding agents | Full product + technical specification (requirements, data model, tools, acceptance criteria) |
| **[AGENTS.md](AGENTS.md)** | Coding agents | Conventions, architecture, file map, Yaala Labs stack, and local commands for AI assistants |

---

## Built with Yaala Labs Agent Kernel

This project is an **Agent Kernel use case** — it uses the open-source [`agentkernel`](https://pypi.org/project/agentkernel/) Python package maintained by **Yaala Labs** to run a production-style multi-agent assistant without building runtime plumbing from scratch.

| Yaala Labs / Agent Kernel capability | How this project uses it |
| --- | --- |
| **Google ADK adapter** (`agentkernel.adk`) | Four Gemini agents in `agent.py`; `GoogleADKModule` bootstraps the runtime in `demo.py` and `whatsapp_app.py` |
| **Tool system** (`agentkernel.core.ToolContext`) | Shop ledger tools in `tool.py`; bound to agents via `GoogleADKToolBuilder` |
| **Multi-agent handoffs** | `ledger_desk` coordinates and transfers to `cashflow_analyst`, `business_advisor`, and `stock_credit_desk` |
| **Session memory** | Active shop + owner name cached per WhatsApp user (`config.yaml` in-memory session store) |
| **CLI** (`agentkernel.cli`) | Interactive agent chat in `demo.py` |
| **REST API** (`agentkernel.api.RESTAPI`) | FastAPI server for WhatsApp webhooks in `whatsapp_app.py` |
| **WhatsApp integration** (`agentkernel.whatsapp`) | `CashflowWhatsAppHandler` extends `AgentWhatsAppRequestHandler` for Meta Cloud API |
| **AWS deployment** (`agentkernel.aws.Lambda`) | Optional serverless entry in `lambda.py` |
| **Config-driven runtime** | `config.yaml` sets session cache, logging, and default WhatsApp agent |

**Framework choice:** Google ADK + **Gemini** (`gemini-3.6-flash`) — not OpenAI, LangGraph, or CrewAI. Installed via:

```toml
agentkernel[cli,adk,api,whatsapp,aws]>=0.8.1
```

**What is custom vs Yaala:** Agent Kernel handles agents, tools, sessions, API, and WhatsApp wiring. This repo adds the **SME domain** (`domain.py`, `store.py`) and deterministic money math so agents never invent balances.

**Docs & repo:** [kernel.yaala.ai/docs](https://kernel.yaala.ai/docs) · [github.com/yaalalabs/agent-kernel](https://github.com/yaalalabs/agent-kernel)

---

## 1. Problem statement

Informal and micro-SMEs in Sri Lanka often track cash in notebooks or memory. Without a simple daily close, stock levels, and customer-credit follow-up, owners discover stock-outs and rent shortfalls too late. Spreadsheets and accounting apps are heavy for a bakery stall or grocery that already lives on WhatsApp.

**Who it affects:** micro shop owners (bakeries, groceries, tea kiosks) who need daily cash visibility but will not adopt complex accounting software.

**What goes wrong today:** late discovery of low cash, forgotten customer credit, stock-outs, and till mismatches at day end.

---

## 2. Solution overview

### What the product does

| Capability | Detail |
| --- | --- |
| Cash ledger | Log sales / expenses; balance + HEALTHY / TIGHT / CRITICAL runway |
| Customer credit | Record who owes the shop, collect payments, age overdue balances |
| Inventory | SKU quantities, reorder levels, low-stock alerts |
| Daily till close | Compare physical till cash vs ledger → variance |
| Trends | This week vs last week (sales / expenses / net) |
| Affordability | “Can I buy flour for 3000?” without breaking runway |
| Alerts | Critical cash, low stock, overdue credit, till mismatch |
| WhatsApp menus | Interactive list + quick buttons for common actions |
| Plain-language log | `sold 12 buns 2400` · `bought flour 1800` · `credit Amara 500` · `paid Amara 200` |

### Agents (Yaala Labs Google ADK runtime)

| Agent | Role |
| --- | --- |
| `ledger_desk` | Default intake: open shop, parse logs, route specialists, till close |
| `cashflow_analyst` | Balance, runway, trends, affordability, dashboard |
| `business_advisor` | Next actions from cash band + overdue credit + low stock |
| `stock_credit_desk` | Inventory and customer credit specialist |

### Architecture

```text
WhatsApp / demo.py / desk.py
            │
            ▼
   Yaala Labs Agent Kernel
   (Google ADK · tools · sessions · REST · WhatsApp)
            │
            ▼
     domain.py  ← deterministic math (no LLM)
            │
            ▼
      store.py  →  SQLite data/shop.db
```

`desk.py` bypasses Agent Kernel and calls `domain.py` / `store.py` directly — useful for judges who want to verify ledger math with no API key.

---

## 3. Setup instructions

### Prerequisites

| Requirement | Required for |
| --- | --- |
| Python **3.12+** | All modes |
| [uv](https://github.com/astral-sh/uv) package manager | Install dependencies |
| Internet access | `uv sync` downloads `agentkernel` from PyPI |
| **Gemini API key** ([Google AI Studio](https://aistudio.google.com/apikey)) | `demo.py`, `whatsapp_app.py` only |
| Meta WhatsApp Cloud API + HTTPS tunnel (ngrok) | `whatsapp_app.py` only |

**Not required for the judge quick start:** no Gemini key, no WhatsApp, no cloud account. Use `desk.py` and `pytest`.

### Clone and install

From the repository root (this project lives inside the Agent Kernel monorepo):

```bash
git clone https://github.com/yaalalabs/agent-kernel.git
cd agent-kernel/use-cases/sme-cashflow-coach
```

**Windows (PowerShell):**

```powershell
uv venv
uv sync --all-extras --dev
```

**macOS / Linux:**

```bash
uv venv
uv sync --all-extras --dev
```

This creates a virtual environment and installs `agentkernel` plus dev tools (`pytest`, etc.).

### Environment variables (optional modes only)

Copy the example file when you want Gemini or WhatsApp:

```powershell
copy .env.example .env
```

Edit `.env` (or export the same variables in your shell):

```env
GOOGLE_API_KEY=your_gemini_api_key
GOOGLE_GENAI_USE_VERTEXAI=FALSE
GEMINI_MODEL=gemini-3.6-flash

# WhatsApp (whatsapp_app.py only)
AK_WHATSAPP__VERIFY_TOKEN=your_secure_verify_token
AK_WHATSAPP__ACCESS_TOKEN=your_permanent_access_token
AK_WHATSAPP__APP_SECRET=your_app_secret
AK_WHATSAPP__PHONE_NUMBER_ID=123456789012345
```

`whatsapp_app.py` loads `.env` automatically from this folder.

---

## 4. How to run the solution

### Quick start for judges (no API keys, ~2 minutes)

Run these commands from `use-cases/sme-cashflow-coach` after `uv sync`:

```powershell
# 1. Load sample bakery ledger into SQLite
uv run python desk.py import data\ledger.example.csv

# 2. Cash summary and runway for the sample shop
uv run python desk.py summary --shop "Nimal Bakery"

# 3. Full dashboard (alerts, trends, stock, credit)
uv run python desk.py dashboard --shop "Nimal Bakery"

# 4. Plain-language logging
uv run python desk.py log "Sold 12 buns 2400" --shop "Nimal Bakery"
uv run python desk.py summary --shop "Nimal Bakery"

# 5. Automated tests (19 tests, no network keys needed)
uv run pytest -q
```

**macOS / Linux:** use forward slashes, e.g. `data/ledger.example.csv`.

**Expected result:** JSON output with balance, runway days, health band (`HEALTHY` / `TIGHT` / `CRITICAL`), and `19 passed` from pytest.

If you see `Multiple shops. Pass --shop ...`, add `--shop "Nimal Bakery"` (or another shop name from `uv run python desk.py shops`).

---

### A) Operational CLI — no LLM (`desk.py`)

Best for verifying ledger math without any API key.

```powershell
uv run python desk.py open --name "Pasindu Bakery" --owner Pasindu --category bakery
uv run python desk.py stock flour 2 --reorder 5 --unit kg --shop "Pasindu Bakery"
uv run python desk.py log "Sold 12 buns 2400" --shop "Pasindu Bakery"
uv run python desk.py credit Amara 500 --note bread --shop "Pasindu Bakery"
uv run python desk.py collect Amara 200 --shop "Pasindu Bakery"
uv run python desk.py close 2000 --shop "Pasindu Bakery"
uv run python desk.py dashboard --shop "Pasindu Bakery"
uv run python desk.py afford 3000 --shop "Pasindu Bakery"
uv run python desk.py advice --shop "Pasindu Bakery"
uv run python desk.py trends --shop "Pasindu Bakery"
```

Import sample data:

```powershell
uv run python desk.py import data\ledger.example.csv
uv run python desk.py summary --shop "Nimal Bakery"
```

List shops: `uv run python desk.py shops`

---

### B) Yaala Labs Agent Kernel CLI with Gemini (`demo.py`)

Uses `GoogleADKModule` + `agentkernel.cli.CLI`. Requires `GOOGLE_API_KEY` in `.env` or your shell.

```powershell
uv run python demo.py
```

Example session:

```text
!select ledger_desk
I'm Pasindu. Open Pasindu Bakery.
Sold 12 buns 2400. Credit Amara 500 bread.
Flour stock is 2 kg, reorder at 5.
Can I buy flour for 3000? What's my dashboard and what should I do?
```

Type `exit` or press Ctrl+C to quit.

---

### C) WhatsApp live demo — Agent Kernel REST + WhatsApp (`whatsapp_app.py`)

Uses Yaala Labs `RESTAPI`, `GoogleADKModule`, and `AgentWhatsAppRequestHandler`. Requires Gemini key **and** Meta WhatsApp Business API credentials.

1. Set all variables in `.env` (see section 3).
2. Start the server:

   ```powershell
   uv run python whatsapp_app.py
   ```

   Server listens on `http://0.0.0.0:8000`.

3. Expose HTTPS (example with ngrok):

   ```powershell
   ngrok http 8000
   ```

4. In [Meta Developer Console](https://developers.facebook.com/) → WhatsApp → Configuration:
   - **Callback URL:** `https://<your-tunnel-host>/whatsapp/webhook`
   - **Verify token:** same as `AK_WHATSAPP__VERIFY_TOKEN`
   - Subscribe to **messages**
5. Add your phone number as a test recipient.

Send `menu`, `hi`, or `help` for the interactive list. Free-text examples:

```text
Sold tea 1500
bought flour 1800
credit Saman 400 bread
paid Saman 200
What's my runway?
Can I buy sugar for 2000?
```

---

### D) Tests

```powershell
uv run pytest -q
```

Runs unit tests for `domain.py`, `store.py`, `menus.py`, and `dedupe.py` — no API keys required.

---

## Troubleshooting

| Issue | Fix |
| --- | --- |
| `Multiple shops. Pass --shop ...` | Add `--shop "Shop Name"` or `--shop SHOP-001` |
| `GOOGLE_API_KEY` missing | Set key in `.env` for `demo.py` / `whatsapp_app.py`; use `desk.py` without a key |
| WhatsApp 401 / no reply | Regenerate `AK_WHATSAPP__ACCESS_TOKEN` in Meta API Setup; restart `whatsapp_app.py` |
| `uv: command not found` | Install uv: https://github.com/astral-sh/uv#installation |
| Wrong Python version | Use Python 3.12+: `uv python install 3.12` |

---

## Project layout

| File | Role |
| --- | --- |
| `README.md` | Judge/human setup and run guide (required submission doc) |
| `SPEC.md` | Coding-agent-readable specification |
| `AGENTS.md` | Agent-readable conventions and architecture |
| `domain.py` | Deterministic cash / credit / alert / parse math |
| `store.py` | SQLite: shops, transactions, inventory, credits, till closes |
| `tool.py` | Agent Kernel tools |
| `agent.py` | Four Gemini/ADK agents |
| `menus.py` | WhatsApp interactive list + button payloads |
| `desk.py` | No-LLM CLI (recommended for judges) |
| `demo.py` | Agent Kernel CLI with Gemini |
| `whatsapp_app.py` | WhatsApp webhook + menus |
| `config.yaml` | Session + WhatsApp agent config |
| `lambda.py` | Optional AWS Lambda entry |
| `data/ledger.example.csv` | Sample ledger for import demo |

---

## Disclaimer

This coach helps owners see cash and take simple operating decisions. It is **not** banking, accounting, tax, or lending advice.
