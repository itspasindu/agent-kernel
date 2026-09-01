from __future__ import annotations

import json

from agentkernel.core import ToolContext

from domain import advice_for, credit_aging, parse_quick_log, top_expense_categories
from store import ShopStore

SHOP_KEY = "sme.active_shop"
OWNER_KEY = "sme.owner"


def _store() -> ShopStore:
    return ShopStore()


def _cache():
    return ToolContext.get().session.get_non_volatile_cache()


def _json(payload: object) -> str:
    return json.dumps(payload, indent=2, default=str)


def _active_shop_id(fallback: str = "") -> str:
    if fallback.strip():
        return fallback.strip()
    try:
        value = _cache().get(SHOP_KEY)
        if value:
            return str(value)
    except RuntimeError:
        pass
    shops = _store().list_shops()
    if len(shops) == 1:
        return shops[0]["id"]
    raise ValueError("No active shop. Call open_shop or select_shop first.")


def _remember_shop(shop_id: str) -> None:
    try:
        _cache().set(SHOP_KEY, shop_id)
    except RuntimeError:
        pass


def set_owner_context(owner_name: str) -> str:
    """Remember which shop owner is using this WhatsApp/CLI session."""
    try:
        _cache().set(OWNER_KEY, owner_name.strip())
    except RuntimeError:
        pass
    return _json({"owner": owner_name.strip()})


def open_shop(name: str, owner_name: str = "", category: str = "", shop_id: str = "") -> str:
    """Create or update a shop ledger. Call this before logging sales for a new business."""
    shop = _store().open_shop(name=name, owner_name=owner_name, category=category, shop_id=shop_id)
    _remember_shop(shop["id"])
    return _json({"shop": shop, "active_shop_id": shop["id"]})


def select_shop(shop_query: str) -> str:
    """Select the active shop for this session by id or unique name."""
    shop = _store().require(shop_query)
    _remember_shop(shop["id"])
    return _json({"shop": shop, "active_shop_id": shop["id"]})


def list_shops() -> str:
    """List every shop ledger on this device."""
    return _json({"shops": _store().list_shops()})


def log_sale(
    amount: str,
    note: str = "",
    category: str = "",
    day: str = "",
    shop_query: str = "",
    sku: str = "",
    quantity: float = 0,
) -> str:
    """Record a cash sale (money in). Amount in LKR. Optional sku/quantity updates inventory."""
    shop_id = _active_shop_id(shop_query)
    result = _store().add_transaction(
        shop_id,
        "sale",
        amount,
        category=category,
        note=note,
        day=day,
        sku=sku,
        quantity=quantity or None,
    )
    _remember_shop(result["shop"]["id"])
    return _json(result)


def log_expense(
    amount: str,
    note: str = "",
    category: str = "",
    day: str = "",
    shop_query: str = "",
    sku: str = "",
    quantity: float = 0,
) -> str:
    """Record an expense (money out). Amount in LKR. Use category='personal' for owner draws."""
    shop_id = _active_shop_id(shop_query)
    result = _store().add_transaction(
        shop_id,
        "expense",
        amount,
        category=category,
        note=note,
        day=day,
        sku=sku,
        quantity=quantity or None,
    )
    _remember_shop(result["shop"]["id"])
    return _json(result)


def parse_and_log(message: str, shop_query: str = "") -> str:
    """Parse a plain WhatsApp line (sold/bought/credit/paid) and apply it. Prefer this for short owner messages."""
    parsed = parse_quick_log(message)
    if not parsed:
        return _json({"ok": False, "error": "Could not parse message. Examples: sold 12 buns 2400 | bought flour 1800 | credit Amara 500 | paid Amara 200"})
    shop_id = _active_shop_id(shop_query)
    intent = parsed["intent"]
    if intent == "sale":
        sku = parsed.get("category") or ""
        qty = parsed.get("quantity")
        if sku and _store().find_stock_item(shop_id, sku) is None:
            sku, qty = "", None
        result = _store().add_transaction(
            shop_id,
            "sale",
            parsed["amount"],
            category=parsed.get("category") or "",
            note=parsed.get("note") or "",
            sku=sku,
            quantity=qty,
        )
        _remember_shop(result["shop"]["id"])
        return _json({"ok": True, "parsed": parsed, **result})
    if intent == "expense":
        sku = parsed.get("category") or ""
        qty = parsed.get("quantity")
        if sku and _store().find_stock_item(shop_id, sku) is None:
            sku, qty = "", None
        result = _store().add_transaction(
            shop_id,
            "expense",
            parsed["amount"],
            category=parsed.get("category") or "",
            note=parsed.get("note") or "",
            sku=sku,
            quantity=qty,
        )
        _remember_shop(result["shop"]["id"])
        return _json({"ok": True, "parsed": parsed, **result})
    if intent == "credit_sale":
        result = _store().add_credit(shop_id, parsed["customer"], parsed["amount"], note=parsed.get("note") or "")
        _remember_shop(shop_id)
        return _json({"ok": True, "parsed": parsed, **result})
    if intent == "credit_payment":
        result = _store().collect_credit(shop_id, parsed["customer"], parsed["amount"])
        _remember_shop(shop_id)
        return _json({"ok": True, "parsed": parsed, **result})
    return _json({"ok": False, "error": f"Unsupported intent: {intent}"})


def list_recent_transactions(limit: int = 10, shop_query: str = "") -> str:
    """List the most recent sales and expenses for the active shop."""
    shop_id = _active_shop_id(shop_query)
    shop = _store().require(shop_id)
    rows = _store().transactions(shop_id, limit=limit)
    return _json({"shop": shop, "transactions": rows})


def get_cash_summary(window_days: int = 7, shop_query: str = "") -> str:
    """Return balance, averages, runway, HEALTHY/TIGHT/CRITICAL. Always call before stating money numbers."""
    shop_id = _active_shop_id(shop_query)
    summary = _store().summary(shop_id, window_days=window_days)
    summary["top_expenses"] = top_expense_categories(_store().all_transactions(shop_id))
    return _json(summary)


def get_runway(shop_query: str = "") -> str:
    """Return how many days of average expenses the current cash balance can cover."""
    shop_id = _active_shop_id(shop_query)
    summary = _store().summary(shop_id)
    return _json(
        {
            "shop": summary["shop"],
            "balance": summary["balance"],
            "avg_daily_expense": summary["avg_daily_expense"],
            "runway_days": summary["runway_days"],
            "band": summary["band"],
            "currency": summary["currency"],
        }
    )


def get_trends(window_days: int = 7, shop_query: str = "") -> str:
    """Compare this week vs last week for sales, expenses, and net daily cash."""
    shop_id = _active_shop_id(shop_query)
    return _json(_store().trends(shop_id, window_days=window_days))


def get_dashboard(shop_query: str = "") -> str:
    """Full shop snapshot: cash summary, trends, inventory, credit aging, till close, and alerts."""
    shop_id = _active_shop_id(shop_query)
    return _json(_store().dashboard(shop_id))


def recommend_actions(shop_query: str = "") -> str:
    """Return up to three practical next actions from cash band + overdue credit + low stock."""
    shop_id = _active_shop_id(shop_query)
    summary = _store().summary(shop_id)
    credits = credit_aging(_store().list_credits(shop_id))
    inventory = _store().list_inventory(shop_id)
    tips = advice_for(summary, summary["shop"], credits=credits, inventory=inventory)
    return _json({"summary": summary, "credits": credits, "inventory": inventory, "actions": tips})


def check_affordability(amount: str, min_runway_days: int = 3, shop_query: str = "") -> str:
    """Check whether spending this amount keeps runway above the safety floor. Call before big stock buys."""
    shop_id = _active_shop_id(shop_query)
    return _json(_store().can_afford(shop_id, amount, min_runway_days=min_runway_days))


def set_stock_item(
    sku: str,
    quantity: float,
    reorder_level: float = 0,
    unit: str = "unit",
    unit_cost: float = 0,
    shop_query: str = "",
) -> str:
    """Set absolute inventory quantity for a SKU (e.g. flour=10 kg, reorder_level=3)."""
    shop_id = _active_shop_id(shop_query)
    item = _store().set_stock(
        shop_id,
        sku=sku,
        quantity=quantity,
        unit=unit,
        reorder_level=reorder_level,
        unit_cost=unit_cost,
    )
    _remember_shop(shop_id)
    return _json({"item": item})


def list_stock(shop_query: str = "") -> str:
    """List inventory with low-stock flags."""
    shop_id = _active_shop_id(shop_query)
    return _json({"shop": _store().require(shop_id), "inventory": _store().list_inventory(shop_id)})


def record_credit(customer: str, amount: str, note: str = "", day: str = "", shop_query: str = "") -> str:
    """Record credit: customer took goods on credit. Cash does not increase until collected."""
    shop_id = _active_shop_id(shop_query)
    result = _store().add_credit(shop_id, customer, amount, note=note, day=day)
    _remember_shop(shop_id)
    return _json(result)


def collect_customer_credit(customer: str, amount: str, day: str = "", shop_query: str = "") -> str:
    """Collect customer credit payment from a customer and log it as cash in."""
    shop_id = _active_shop_id(shop_query)
    result = _store().collect_credit(shop_id, customer, amount, day=day)
    _remember_shop(shop_id)
    return _json(result)


def list_customer_credits(shop_query: str = "") -> str:
    """List open customer credit (credit) with aging."""
    shop_id = _active_shop_id(shop_query)
    credits = _store().list_credits(shop_id)
    return _json({"shop": _store().require(shop_id), "credits": credits, "aging": credit_aging(credits)})


def close_till(till_count: str, day: str = "", note: str = "", shop_query: str = "") -> str:
    """Daily close: compare physical till cash to ledger balance and store the variance."""
    shop_id = _active_shop_id(shop_query)
    result = _store().daily_close(shop_id, till_count, day=day, note=note)
    _remember_shop(shop_id)
    return _json(result)


def import_ledger_csv(csv_path: str, shop_query: str = "") -> str:
    """Import sales/expenses from a CSV ledger file on this machine."""
    result = _store().import_csv(csv_path, shop_query=shop_query)
    if result.get("shop"):
        _remember_shop(result["shop"]["id"])
    return _json(result)


TOOLS = [
    set_owner_context,
    open_shop,
    select_shop,
    list_shops,
    parse_and_log,
    log_sale,
    log_expense,
    list_recent_transactions,
    get_cash_summary,
    get_runway,
    get_trends,
    get_dashboard,
    recommend_actions,
    check_affordability,
    set_stock_item,
    list_stock,
    record_credit,
    collect_customer_credit,
    list_customer_credits,
    close_till,
    import_ledger_csv,
]
