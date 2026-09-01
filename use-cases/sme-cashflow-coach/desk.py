"""Shop ledger CLI that writes the live SQLite database without using an LLM."""

from __future__ import annotations

import argparse
import json
import sys

from domain import advice_for, credit_aging, parse_quick_log
from store import ShopStore


def _print(payload: object) -> None:
    print(json.dumps(payload, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SME cashflow ledger (no LLM required).")
    sub = parser.add_subparsers(dest="command", required=True)

    open_cmd = sub.add_parser("open", help="Open or update a shop")
    open_cmd.add_argument("--name", required=True)
    open_cmd.add_argument("--owner", default="")
    open_cmd.add_argument("--category", default="")
    open_cmd.add_argument("--id", default="")

    sub.add_parser("shops", help="List shops")

    sale = sub.add_parser("sale", help="Log a sale")
    sale.add_argument("amount")
    sale.add_argument("--note", default="")
    sale.add_argument("--category", default="")
    sale.add_argument("--day", default="")
    sale.add_argument("--shop", default="")
    sale.add_argument("--sku", default="")
    sale.add_argument("--qty", type=float, default=0)

    expense = sub.add_parser("expense", help="Log an expense")
    expense.add_argument("amount")
    expense.add_argument("--note", default="")
    expense.add_argument("--category", default="")
    expense.add_argument("--day", default="")
    expense.add_argument("--shop", default="")
    expense.add_argument("--sku", default="")
    expense.add_argument("--qty", type=float, default=0)

    quick = sub.add_parser("log", help="Parse a plain line: sold 12 buns 2400")
    quick.add_argument("message")
    quick.add_argument("--shop", default="")

    recent = sub.add_parser("recent", help="Recent transactions")
    recent.add_argument("--shop", default="")
    recent.add_argument("--limit", type=int, default=10)

    summary = sub.add_parser("summary", help="Cash summary and runway")
    summary.add_argument("--shop", default="")
    summary.add_argument("--days", type=int, default=7)

    trends = sub.add_parser("trends", help="This week vs last week")
    trends.add_argument("--shop", default="")
    trends.add_argument("--days", type=int, default=7)

    dash = sub.add_parser("dashboard", help="Full snapshot + alerts")
    dash.add_argument("--shop", default="")

    advice = sub.add_parser("advice", help="Recommended actions")
    advice.add_argument("--shop", default="")

    afford = sub.add_parser("afford", help="Can I spend this amount?")
    afford.add_argument("amount")
    afford.add_argument("--shop", default="")
    afford.add_argument("--min-runway", type=int, default=3)

    stock = sub.add_parser("stock", help="Set inventory quantity")
    stock.add_argument("sku")
    stock.add_argument("quantity", type=float)
    stock.add_argument("--reorder", type=float, default=0)
    stock.add_argument("--unit", default="unit")
    stock.add_argument("--cost", type=float, default=0)
    stock.add_argument("--shop", default="")

    inv = sub.add_parser("inventory", help="List inventory")
    inv.add_argument("--shop", default="")

    credit = sub.add_parser("credit", help="Record customer credit")
    credit.add_argument("customer")
    credit.add_argument("amount")
    credit.add_argument("--note", default="")
    credit.add_argument("--shop", default="")

    collect = sub.add_parser("collect", help="Collect customer credit")
    collect.add_argument("customer")
    collect.add_argument("amount")
    collect.add_argument("--shop", default="")

    credits_cmd = sub.add_parser("credits", help="List open credit")
    credits_cmd.add_argument("--shop", default="")

    close = sub.add_parser("close", help="Daily till close")
    close.add_argument("till_count")
    close.add_argument("--day", default="")
    close.add_argument("--note", default="")
    close.add_argument("--shop", default="")

    imp = sub.add_parser("import", help="Import a CSV ledger")
    imp.add_argument("csv_path")
    imp.add_argument("--shop", default="")

    args = parser.parse_args(argv)
    store = ShopStore()

    def _shop_ref() -> str:
        if getattr(args, "shop", ""):
            return args.shop
        shops = store.list_shops()
        if len(shops) == 1:
            return shops[0]["id"]
        if not shops:
            raise SystemExit("No shop yet. Run: python desk.py open --name \"Nimal's Bakery\"")
        raise SystemExit("Multiple shops. Pass --shop SHOP-001 or a unique name.")

    if args.command == "open":
        shop = store.open_shop(name=args.name, owner_name=args.owner, category=args.category, shop_id=args.id)
        _print({"shop": shop})
        return 0
    if args.command == "shops":
        _print({"shops": store.list_shops()})
        return 0
    if args.command == "sale":
        _print(
            store.add_transaction(
                _shop_ref(),
                "sale",
                args.amount,
                category=args.category,
                note=args.note,
                day=args.day,
                sku=args.sku,
                quantity=args.qty or None,
            )
        )
        return 0
    if args.command == "expense":
        _print(
            store.add_transaction(
                _shop_ref(),
                "expense",
                args.amount,
                category=args.category,
                note=args.note,
                day=args.day,
                sku=args.sku,
                quantity=args.qty or None,
            )
        )
        return 0
    if args.command == "log":
        parsed = parse_quick_log(args.message)
        if not parsed:
            raise SystemExit("Could not parse message")
        shop_id = _shop_ref()
        sku = parsed.get("category") or ""
        qty = parsed.get("quantity")
        if sku and store.find_stock_item(shop_id, sku) is None:
            sku, qty = "", None
        if parsed["intent"] == "sale":
            _print(
                store.add_transaction(
                    shop_id,
                    "sale",
                    parsed["amount"],
                    category=parsed.get("category") or "",
                    note=parsed.get("note") or "",
                    sku=sku,
                    quantity=qty,
                )
            )
        elif parsed["intent"] == "expense":
            _print(
                store.add_transaction(
                    shop_id,
                    "expense",
                    parsed["amount"],
                    category=parsed.get("category") or "",
                    note=parsed.get("note") or "",
                    sku=sku,
                    quantity=qty,
                )
            )
        elif parsed["intent"] == "credit_sale":
            _print(store.add_credit(shop_id, parsed["customer"], parsed["amount"], note=parsed.get("note") or ""))
        elif parsed["intent"] == "credit_payment":
            _print(store.collect_credit(shop_id, parsed["customer"], parsed["amount"]))
        return 0
    if args.command == "recent":
        shop = store.require(_shop_ref())
        _print({"shop": shop, "transactions": store.transactions(shop["id"], limit=args.limit)})
        return 0
    if args.command == "summary":
        _print(store.summary(_shop_ref(), window_days=args.days))
        return 0
    if args.command == "trends":
        _print(store.trends(_shop_ref(), window_days=args.days))
        return 0
    if args.command == "dashboard":
        _print(store.dashboard(_shop_ref()))
        return 0
    if args.command == "advice":
        summary_payload = store.summary(_shop_ref())
        credits = credit_aging(store.list_credits(_shop_ref()))
        inventory = store.list_inventory(_shop_ref())
        _print(
            {
                "summary": summary_payload,
                "actions": advice_for(summary_payload, summary_payload["shop"], credits=credits, inventory=inventory),
            }
        )
        return 0
    if args.command == "afford":
        _print(store.can_afford(_shop_ref(), args.amount, min_runway_days=args.min_runway))
        return 0
    if args.command == "stock":
        _print(
            store.set_stock(
                _shop_ref(),
                sku=args.sku,
                quantity=args.quantity,
                unit=args.unit,
                reorder_level=args.reorder,
                unit_cost=args.cost,
            )
        )
        return 0
    if args.command == "inventory":
        _print({"inventory": store.list_inventory(_shop_ref())})
        return 0
    if args.command == "credit":
        _print(store.add_credit(_shop_ref(), args.customer, args.amount, note=args.note))
        return 0
    if args.command == "collect":
        _print(store.collect_credit(_shop_ref(), args.customer, args.amount))
        return 0
    if args.command == "credits":
        credits = store.list_credits(_shop_ref())
        _print({"credits": credits, "aging": credit_aging(credits)})
        return 0
    if args.command == "close":
        _print(store.daily_close(_shop_ref(), args.till_count, day=args.day, note=args.note))
        return 0
    if args.command == "import":
        _print(store.import_csv(args.csv_path, shop_query=args.shop))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
