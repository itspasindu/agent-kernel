"""Deterministic cashflow math for a micro-SME ledger.

Balances, runway, alerts, and affordability are computed from recorded data so agents
never invent numbers.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

ADVICE: list[dict[str, str]] = [
    {
        "id": "hold-cash",
        "band": "HEALTHY",
        "title": "Hold a cash buffer",
        "action": "Keep at least 7 days of average expenses as a buffer before new stock buys.",
    },
    {
        "id": "track-daily",
        "band": "HEALTHY",
        "title": "Log every sale and expense",
        "action": "Send WhatsApp lines like 'sold 12 buns 2400' or 'bought flour 1800' at close of day.",
    },
    {
        "id": "cut-discretionary",
        "band": "TIGHT",
        "title": "Pause non-essential spend",
        "action": "Delay packaging upgrades and small personal draws until runway is above 7 days.",
    },
    {
        "id": "restock-top-seller",
        "band": "TIGHT",
        "title": "Restock only the top seller",
        "action": "Spend on the item that sold most this week; skip slow movers for now.",
    },
    {
        "id": "raise-price-check",
        "band": "TIGHT",
        "title": "Check margin on top SKU",
        "action": "Compare last purchase cost vs selling price; if margin is thin, nudge price or portion size.",
    },
    {
        "id": "emergency-cash",
        "band": "CRITICAL",
        "title": "Protect remaining cash",
        "action": "Stop non-stock purchases today. Sell existing stock first. Avoid new credit.",
    },
    {
        "id": "daily-close",
        "band": "CRITICAL",
        "title": "Do a same-day cash close",
        "action": "Count till cash tonight and log every expense so tomorrow's plan is based on truth.",
    },
    {
        "id": "supplier-negotiate",
        "band": "CRITICAL",
        "title": "Ask supplier for smaller lot",
        "action": "Buy half the usual flour/stock quantity this week to stretch runway.",
    },
    {
        "id": "collect-credit",
        "band": "TIGHT",
        "title": "Collect overdue customer credit",
        "action": "Call customers with credit older than 7 days before buying more stock.",
    },
    {
        "id": "restock-low",
        "band": "HEALTHY",
        "title": "Restock low items",
        "action": "Top up SKUs that are at or below reorder level while cash is healthy.",
    },
]


def normalize_day(value: str | date | None) -> date:
    if value is None or value == "":
        return date.today()
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return date.today()


def parse_amount(raw: Any) -> float:
    """Parse amounts like 2400, 2,400.50, LKR 1800, Rs.500."""
    if isinstance(raw, (int, float)):
        return round(float(raw), 2)
    text = str(raw).strip().lower()
    for token in ("lkr", "rs.", "rs", "රු", ","):
        text = text.replace(token, "")
    text = text.strip()
    if not text:
        raise ValueError("amount is empty")
    return round(float(text), 2)


def parse_quick_log(text: str) -> dict[str, Any] | None:
    """Deterministically parse common WhatsApp log lines.

    Examples:
      sold 12 buns 2400
      sale tea 1500
      bought flour 1800
      expense gas 800
      credit amara 500 bread
      paid amara 200
    """
    raw = " ".join(str(text).strip().lower().split())
    if not raw:
        return None

    sale = re.match(
        r"^(?:sold|sale|sell)\s+(?:(\d+(?:\.\d+)?)\s+)?(.+?)\s+(?:for\s+)?(?:lkr\s*|rs\.?\s*)?(\d[\d,]*(?:\.\d+)?)$",
        raw,
    )
    if sale:
        qty, note, amount = sale.groups()
        return {
            "intent": "sale",
            "amount": parse_amount(amount),
            "note": note.strip(),
            "category": note.strip().split()[-1] if note else "",
            "quantity": float(qty) if qty else None,
        }

    expense = re.match(
        r"^(?:bought|buy|expense|spent|pay(?:ment)? for)\s+(.+?)\s+(?:for\s+)?(?:lkr\s*|rs\.?\s*)?(\d[\d,]*(?:\.\d+)?)$",
        raw,
    )
    if expense:
        note, amount = expense.groups()
        return {
            "intent": "expense",
            "amount": parse_amount(amount),
            "note": note.strip(),
            "category": note.strip().split()[0] if note else "supplies",
            "quantity": None,
        }

    credit = re.match(
        r"^(?:credit|owe[sd]?)\s+([a-z][\w\s]{0,40}?)\s+(?:lkr\s*|rs\.?\s*)?(\d[\d,]*(?:\.\d+)?)(?:\s+(.+))?$",
        raw,
    )
    if credit:
        customer, amount, note = credit.groups()
        return {
            "intent": "credit_sale",
            "customer": customer.strip(),
            "amount": parse_amount(amount),
            "note": (note or "customer credit").strip(),
        }

    paid = re.match(
        r"^(?:paid|collect(?:ed)?|received)\s+([a-z][\w\s]{0,40}?)\s+(?:lkr\s*|rs\.?\s*)?(\d[\d,]*(?:\.\d+)?)$",
        raw,
    )
    if paid:
        customer, amount = paid.groups()
        return {
            "intent": "credit_payment",
            "customer": customer.strip(),
            "amount": parse_amount(amount),
        }

    return None


def balance_from_transactions(transactions: list[dict[str, Any]]) -> float:
    total = 0.0
    for row in transactions:
        amount = float(row["amount"])
        if row["kind"] == "sale":
            total += amount
        elif row["kind"] == "expense":
            total -= amount
    return round(total, 2)


def summarize_cashflow(
    transactions: list[dict[str, Any]],
    *,
    as_of: date | None = None,
    window_days: int = 7,
) -> dict[str, Any]:
    """Compute balance, window averages, and runway from the ledger."""
    today = as_of or date.today()
    start = today - timedelta(days=max(1, window_days) - 1)
    balance = balance_from_transactions(transactions)

    window = [row for row in transactions if start <= normalize_day(row.get("day")) <= today]
    sales = sum(float(row["amount"]) for row in window if row["kind"] == "sale")
    expenses = sum(float(row["amount"]) for row in window if row["kind"] == "expense")
    owner_draws = sum(
        float(row["amount"])
        for row in window
        if row["kind"] == "expense"
        and str(row.get("category") or "").lower() in {"personal", "draw", "owner", "owner_draw"}
    )
    days = max(1, window_days)
    avg_daily_sales = round(sales / days, 2)
    avg_daily_expense = round(expenses / days, 2)
    net_daily = round(avg_daily_sales - avg_daily_expense, 2)

    if avg_daily_expense <= 0:
        runway_days = 999 if balance >= 0 else 0
    else:
        runway_days = max(0, int(balance // avg_daily_expense))

    band = health_band(balance=balance, runway_days=runway_days, net_daily=net_daily)
    return {
        "currency": "LKR",
        "as_of": today.isoformat(),
        "window_days": window_days,
        "balance": balance,
        "sales_in_window": round(sales, 2),
        "expenses_in_window": round(expenses, 2),
        "owner_draws_in_window": round(owner_draws, 2),
        "avg_daily_sales": avg_daily_sales,
        "avg_daily_expense": avg_daily_expense,
        "net_daily": net_daily,
        "runway_days": runway_days,
        "band": band,
        "transaction_count": len(transactions),
        "window_transaction_count": len(window),
    }


def compare_windows(
    transactions: list[dict[str, Any]],
    *,
    as_of: date | None = None,
    window_days: int = 7,
) -> dict[str, Any]:
    """Compare this window vs the previous window of equal length."""
    today = as_of or date.today()
    current = summarize_cashflow(transactions, as_of=today, window_days=window_days)
    previous_end = today - timedelta(days=window_days)
    previous = summarize_cashflow(transactions, as_of=previous_end, window_days=window_days)

    def delta(cur: float, prev: float) -> dict[str, float]:
        return {"current": cur, "previous": prev, "change": round(cur - prev, 2)}

    return {
        "window_days": window_days,
        "sales": delta(current["sales_in_window"], previous["sales_in_window"]),
        "expenses": delta(current["expenses_in_window"], previous["expenses_in_window"]),
        "net_daily": delta(current["net_daily"], previous["net_daily"]),
        "balance": current["balance"],
        "band": current["band"],
        "runway_days": current["runway_days"],
        "current": current,
        "previous": previous,
    }


def health_band(*, balance: float, runway_days: int, net_daily: float) -> str:
    if balance < 0 or runway_days < 3:
        return "CRITICAL"
    if runway_days < 7 or net_daily < 0:
        return "TIGHT"
    return "HEALTHY"


def affordability(
    summary: dict[str, Any],
    purchase_amount: float,
    *,
    min_runway_days: int = 3,
) -> dict[str, Any]:
    """Can the shop spend `purchase_amount` without dropping below a runway floor?"""
    amount = parse_amount(purchase_amount)
    balance = float(summary["balance"])
    avg_expense = float(summary["avg_daily_expense"] or 0)
    projected_balance = round(balance - amount, 2)
    if avg_expense <= 0:
        projected_runway = 999 if projected_balance >= 0 else 0
    else:
        projected_runway = max(0, int(projected_balance // avg_expense))
    safe = projected_balance >= 0 and projected_runway >= min_runway_days
    return {
        "amount": amount,
        "current_balance": balance,
        "projected_balance": projected_balance,
        "current_runway_days": summary["runway_days"],
        "projected_runway_days": projected_runway,
        "min_runway_days": min_runway_days,
        "safe": safe,
        "recommendation": (
            "Safe to buy if stock will sell soon."
            if safe
            else "Do not buy yet — protect cash / collect customer credit / cut draws first."
        ),
    }


def credit_aging(entries: list[dict[str, Any]], *, as_of: date | None = None) -> list[dict[str, Any]]:
    """Summarize outstanding customer credit with age in days."""
    today = as_of or date.today()
    aged = []
    for row in entries:
        outstanding = float(row.get("outstanding") or 0)
        if outstanding <= 0:
            continue
        opened = normalize_day(row.get("opened_on") or row.get("day"))
        age_days = max(0, (today - opened).days)
        aged.append(
            {
                "customer": row["customer"],
                "outstanding": outstanding,
                "opened_on": opened.isoformat(),
                "age_days": age_days,
                "overdue": age_days >= 7,
                "note": row.get("note") or "",
            }
        )
    return sorted(aged, key=lambda item: (-item["outstanding"], -item["age_days"]))


def build_alerts(
    *,
    summary: dict[str, Any],
    inventory: list[dict[str, Any]] | None = None,
    credits: list[dict[str, Any]] | None = None,
    last_close: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Deterministic operational alerts for WhatsApp."""
    alerts: list[dict[str, str]] = []
    band = summary.get("band")
    if band == "CRITICAL":
        alerts.append(
            {
                "code": "cash-critical",
                "severity": "high",
                "message": f"Cash band CRITICAL — balance LKR {summary['balance']}, runway {summary['runway_days']} day(s).",
            }
        )
    elif band == "TIGHT":
        alerts.append(
            {
                "code": "cash-tight",
                "severity": "medium",
                "message": f"Cash band TIGHT — runway {summary['runway_days']} day(s). Pause non-essential spend.",
            }
        )

    draws = float(summary.get("owner_draws_in_window") or 0)
    expenses = float(summary.get("expenses_in_window") or 0)
    if expenses > 0 and draws / expenses >= 0.35:
        alerts.append(
            {
                "code": "high-owner-draw",
                "severity": "medium",
                "message": f"Owner draws are {round(100 * draws / expenses)}% of expenses this window.",
            }
        )

    for item in inventory or []:
        qty = float(item.get("quantity") or 0)
        reorder = float(item.get("reorder_level") or 0)
        if qty <= reorder:
            alerts.append(
                {
                    "code": "low-stock",
                    "severity": "medium",
                    "message": f"Low stock: {item['sku']} has {qty} left (reorder at {reorder}).",
                }
            )

    overdue = [row for row in (credits or []) if row.get("overdue") and float(row.get("outstanding") or 0) > 0]
    if overdue:
        total = round(sum(float(row["outstanding"]) for row in overdue), 2)
        alerts.append(
            {
                "code": "credit-overdue",
                "severity": "high",
                "message": f"{len(overdue)} customer(s) overdue on credit — LKR {total} outstanding.",
            }
        )

    if last_close and last_close.get("variance") is not None:
        variance = float(last_close["variance"])
        if abs(variance) >= 100:
            alerts.append(
                {
                    "code": "till-mismatch",
                    "severity": "high",
                    "message": f"Last till close variance LKR {variance}. Recount cash and missing receipts.",
                }
            )

    severity_rank = {"high": 0, "medium": 1, "low": 2}
    return sorted(alerts, key=lambda row: severity_rank.get(row["severity"], 9))


def advice_for(
    summary: dict[str, Any],
    shop: dict[str, Any] | None = None,
    *,
    credits: list[dict[str, Any]] | None = None,
    inventory: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    band = summary["band"]
    picks = [dict(item) for item in ADVICE if item["band"] == band]

    if any(row.get("overdue") for row in (credits or [])):
        picks.insert(0, next(item for item in ADVICE if item["id"] == "collect-credit"))
    if inventory and any(float(i.get("quantity") or 0) <= float(i.get("reorder_level") or 0) for i in inventory):
        if band == "HEALTHY":
            picks.insert(0, next(item for item in ADVICE if item["id"] == "restock-low"))

    if band == "TIGHT" and float(summary.get("avg_daily_sales") or 0) > 0:
        order = {"collect-credit": 0, "cut-discretionary": 1, "restock-top-seller": 2, "raise-price-check": 3}
        picks = sorted(picks, key=lambda item: order.get(item["id"], 9))

    # de-dupe by id
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for item in picks:
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        if shop and shop.get("category"):
            item = dict(item)
            item["context"] = f"Shop category: {shop['category']}"
        unique.append(item)
    return unique[:3]


def top_expense_categories(transactions: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    buckets: dict[str, float] = {}
    for row in transactions:
        if row["kind"] != "expense":
            continue
        label = (row.get("category") or row.get("note") or "other").strip().lower() or "other"
        buckets[label] = round(buckets.get(label, 0.0) + float(row["amount"]), 2)
    ranked = sorted(buckets.items(), key=lambda pair: pair[1], reverse=True)
    return [{"category": name, "amount": amount} for name, amount in ranked[:limit]]


def top_sale_categories(transactions: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    buckets: dict[str, float] = {}
    for row in transactions:
        if row["kind"] != "sale":
            continue
        label = (row.get("category") or row.get("note") or "other").strip().lower() or "other"
        buckets[label] = round(buckets.get(label, 0.0) + float(row["amount"]), 2)
    ranked = sorted(buckets.items(), key=lambda pair: pair[1], reverse=True)
    return [{"category": name, "amount": amount} for name, amount in ranked[:limit]]
