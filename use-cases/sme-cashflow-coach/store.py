"""SQLite-backed shop ledger with inventory, customer credit, and daily till closes."""

from __future__ import annotations

import csv
import os
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from domain import (
    affordability,
    balance_from_transactions,
    build_alerts,
    compare_windows,
    credit_aging,
    normalize_day,
    parse_amount,
    summarize_cashflow,
    top_expense_categories,
    top_sale_categories,
)

DEFAULT_DB = Path(__file__).resolve().parent / "data" / "shop.db"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class ShopStore:
    def __init__(self, db_path: Path | str | None = None) -> None:
        env_path = os.environ.get("SHOP_DB")
        self.path = Path(db_path or env_path or DEFAULT_DB)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS shops (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    owner_name TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT '',
                    currency TEXT NOT NULL DEFAULT 'LKR',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    shop_id TEXT NOT NULL,
                    kind TEXT NOT NULL CHECK (kind IN ('sale', 'expense')),
                    amount REAL NOT NULL,
                    category TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    day TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (shop_id) REFERENCES shops(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_tx_shop_day ON transactions(shop_id, day);
                CREATE TABLE IF NOT EXISTS inventory (
                    shop_id TEXT NOT NULL,
                    sku TEXT NOT NULL,
                    quantity REAL NOT NULL DEFAULT 0,
                    unit TEXT NOT NULL DEFAULT 'unit',
                    reorder_level REAL NOT NULL DEFAULT 0,
                    unit_cost REAL NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (shop_id, sku),
                    FOREIGN KEY (shop_id) REFERENCES shops(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS credits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    shop_id TEXT NOT NULL,
                    customer TEXT NOT NULL,
                    amount REAL NOT NULL,
                    paid REAL NOT NULL DEFAULT 0,
                    note TEXT NOT NULL DEFAULT '',
                    opened_on TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (shop_id) REFERENCES shops(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_credits_shop ON credits(shop_id, customer);
                CREATE TABLE IF NOT EXISTS daily_closes (
                    shop_id TEXT NOT NULL,
                    day TEXT NOT NULL,
                    till_count REAL NOT NULL,
                    ledger_balance REAL NOT NULL,
                    variance REAL NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (shop_id, day),
                    FOREIGN KEY (shop_id) REFERENCES shops(id) ON DELETE CASCADE
                );
                """
            )

    def _next_shop_id(self, conn: sqlite3.Connection) -> str:
        row = conn.execute("SELECT id FROM shops ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return "SHOP-001"
        digits = "".join(ch for ch in row["id"] if ch.isdigit())
        number = int(digits) + 1 if digits else 1
        return f"SHOP-{number:03d}"

    def open_shop(
        self,
        name: str,
        owner_name: str = "",
        category: str = "",
        shop_id: str = "",
        currency: str = "LKR",
    ) -> dict[str, Any]:
        with self._connect() as conn:
            sid = shop_id.strip() or self._next_shop_id(conn)
            existing = conn.execute("SELECT id FROM shops WHERE id = ?", (sid,)).fetchone()
            if existing:
                conn.execute(
                    """
                    UPDATE shops
                    SET name = ?, owner_name = COALESCE(NULLIF(?, ''), owner_name),
                        category = COALESCE(NULLIF(?, ''), category),
                        currency = ?
                    WHERE id = ?
                    """,
                    (name.strip(), owner_name.strip(), category.strip(), currency.strip() or "LKR", sid),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO shops (id, name, owner_name, category, currency, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sid,
                        name.strip(),
                        owner_name.strip(),
                        category.strip(),
                        currency.strip() or "LKR",
                        _utc_now(),
                    ),
                )
        return self.require(sid)

    def list_shops(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM shops ORDER BY id").fetchall()
            return [self._shop_dict(row) for row in rows]

    def find_shop(self, query: str) -> dict[str, Any] | None:
        needle = query.strip().lower()
        if not needle:
            return None
        shops = self.list_shops()
        exact = [shop for shop in shops if shop["id"].lower() == needle]
        if len(exact) == 1:
            return exact[0]
        matches = [shop for shop in shops if needle in shop["name"].lower() or needle in shop["id"].lower()]
        if len(matches) == 1:
            return matches[0]
        return None

    def require(self, query: str) -> dict[str, Any]:
        shop = self.find_shop(query)
        if not shop:
            raise ValueError(f"Shop not found: {query!r}. Open a shop first or use an exact name/id.")
        return shop

    def _shop_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "name": row["name"],
            "owner_name": row["owner_name"],
            "category": row["category"],
            "currency": row["currency"],
            "created_at": row["created_at"],
        }

    def _tx_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "shop_id": row["shop_id"],
            "kind": row["kind"],
            "amount": float(row["amount"]),
            "category": row["category"],
            "note": row["note"],
            "day": row["day"],
            "created_at": row["created_at"],
        }

    def add_transaction(
        self,
        shop_query: str,
        kind: str,
        amount: Any,
        category: str = "",
        note: str = "",
        day: str = "",
        *,
        sku: str = "",
        quantity: float | None = None,
    ) -> dict[str, Any]:
        kind_norm = kind.strip().lower()
        if kind_norm not in {"sale", "expense"}:
            raise ValueError("kind must be 'sale' or 'expense'")
        shop = self.require(shop_query)
        value = parse_amount(amount)
        if value <= 0:
            raise ValueError("amount must be positive")
        day_iso = normalize_day(day.strip() or date.today().isoformat()).isoformat()

        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO transactions (shop_id, kind, amount, category, note, day, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    shop["id"],
                    kind_norm,
                    value,
                    category.strip(),
                    note.strip(),
                    day_iso,
                    _utc_now(),
                ),
            )
            tx_id = int(cur.lastrowid)

        inventory_update = None
        if sku.strip() and quantity is not None:
            delta = -abs(float(quantity)) if kind_norm == "sale" else abs(float(quantity))
            inventory_update = self.adjust_stock(
                shop["id"],
                sku=sku,
                delta=delta,
                unit_cost=value / float(quantity) if kind_norm == "expense" and float(quantity) else 0,
            )

        txs = self.all_transactions(shop["id"])
        return {
            "transaction": next(row for row in txs if row["id"] == tx_id),
            "summary": summarize_cashflow(txs),
            "shop": shop,
            "inventory": inventory_update,
        }

    def transactions(self, shop_query: str, limit: int = 50) -> list[dict[str, Any]]:
        shop = self.require(shop_query)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM transactions
                WHERE shop_id = ?
                ORDER BY day DESC, id DESC
                LIMIT ?
                """,
                (shop["id"], max(1, int(limit))),
            ).fetchall()
            return [self._tx_dict(row) for row in rows]

    def all_transactions(self, shop_query: str) -> list[dict[str, Any]]:
        shop = self.require(shop_query)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM transactions
                WHERE shop_id = ?
                ORDER BY day ASC, id ASC
                """,
                (shop["id"],),
            ).fetchall()
            return [self._tx_dict(row) for row in rows]

    def summary(self, shop_query: str, window_days: int = 7) -> dict[str, Any]:
        shop = self.require(shop_query)
        txs = self.all_transactions(shop["id"])
        payload = summarize_cashflow(txs, window_days=window_days)
        payload["shop"] = shop
        payload["balance_check"] = balance_from_transactions(txs)
        payload["top_expenses"] = top_expense_categories(txs)
        payload["top_sales"] = top_sale_categories(txs)
        return payload

    def trends(self, shop_query: str, window_days: int = 7) -> dict[str, Any]:
        shop = self.require(shop_query)
        txs = self.all_transactions(shop["id"])
        payload = compare_windows(txs, window_days=window_days)
        payload["shop"] = shop
        return payload

    def set_stock(
        self,
        shop_query: str,
        sku: str,
        quantity: float,
        unit: str = "unit",
        reorder_level: float = 0,
        unit_cost: float = 0,
    ) -> dict[str, Any]:
        shop = self.require(shop_query)
        sku_norm = sku.strip().lower()
        if not sku_norm:
            raise ValueError("sku is required")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO inventory (shop_id, sku, quantity, unit, reorder_level, unit_cost, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(shop_id, sku) DO UPDATE SET
                    quantity = excluded.quantity,
                    unit = excluded.unit,
                    reorder_level = excluded.reorder_level,
                    unit_cost = CASE WHEN excluded.unit_cost > 0 THEN excluded.unit_cost ELSE inventory.unit_cost END,
                    updated_at = excluded.updated_at
                """,
                (
                    shop["id"],
                    sku_norm,
                    float(quantity),
                    unit.strip() or "unit",
                    float(reorder_level),
                    float(unit_cost or 0),
                    _utc_now(),
                ),
            )
        return self.get_stock_item(shop["id"], sku_norm)

    def adjust_stock(
        self,
        shop_query: str,
        sku: str,
        delta: float,
        unit: str = "unit",
        reorder_level: float | None = None,
        unit_cost: float = 0,
    ) -> dict[str, Any]:
        shop = self.require(shop_query)
        sku_norm = sku.strip().lower()
        current = self.find_stock_item(shop["id"], sku_norm)
        qty = float(current["quantity"]) + float(delta) if current else float(delta)
        if qty < 0:
            qty = 0
        return self.set_stock(
            shop["id"],
            sku=sku_norm,
            quantity=qty,
            unit=(current or {}).get("unit") or unit,
            reorder_level=float(reorder_level) if reorder_level is not None else float((current or {}).get("reorder_level") or 0),
            unit_cost=unit_cost or float((current or {}).get("unit_cost") or 0),
        )

    def find_stock_item(self, shop_query: str, sku: str) -> dict[str, Any] | None:
        shop = self.require(shop_query)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM inventory WHERE shop_id = ? AND sku = ?",
                (shop["id"], sku.strip().lower()),
            ).fetchone()
            return self._stock_dict(row) if row else None

    def get_stock_item(self, shop_query: str, sku: str) -> dict[str, Any]:
        item = self.find_stock_item(shop_query, sku)
        if not item:
            raise ValueError(f"Stock item not found: {sku!r}")
        return item

    def list_inventory(self, shop_query: str) -> list[dict[str, Any]]:
        shop = self.require(shop_query)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM inventory WHERE shop_id = ? ORDER BY sku",
                (shop["id"],),
            ).fetchall()
            return [self._stock_dict(row) for row in rows]

    def _stock_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        qty = float(row["quantity"])
        reorder = float(row["reorder_level"])
        return {
            "shop_id": row["shop_id"],
            "sku": row["sku"],
            "quantity": qty,
            "unit": row["unit"],
            "reorder_level": reorder,
            "unit_cost": float(row["unit_cost"]),
            "low_stock": qty <= reorder,
            "updated_at": row["updated_at"],
        }

    def add_credit(
        self,
        shop_query: str,
        customer: str,
        amount: Any,
        note: str = "",
        day: str = "",
    ) -> dict[str, Any]:
        """Record customer credit (customer owes the shop). Does not change cash until collected."""
        shop = self.require(shop_query)
        value = parse_amount(amount)
        if value <= 0:
            raise ValueError("amount must be positive")
        customer_norm = customer.strip()
        if not customer_norm:
            raise ValueError("customer is required")
        day_iso = normalize_day(day.strip() or date.today().isoformat()).isoformat()
        with self._connect() as conn:
            # Prefer rolling up into an open credit line for the same customer.
            open_row = conn.execute(
                """
                SELECT id, amount, paid FROM credits
                WHERE shop_id = ? AND lower(customer) = lower(?) AND amount > paid
                ORDER BY opened_on ASC, id ASC LIMIT 1
                """,
                (shop["id"], customer_norm),
            ).fetchone()
            if open_row:
                conn.execute(
                    "UPDATE credits SET amount = amount + ?, note = CASE WHEN ? != '' THEN ? ELSE note END, updated_at = ? WHERE id = ?",
                    (value, note.strip(), note.strip(), _utc_now(), open_row["id"]),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO credits (shop_id, customer, amount, paid, note, opened_on, updated_at)
                    VALUES (?, ?, ?, 0, ?, ?, ?)
                    """,
                    (shop["id"], customer_norm, value, note.strip(), day_iso, _utc_now()),
                )
        return {
            "shop": shop,
            "credits": self.list_credits(shop["id"]),
            "aging": credit_aging(self.list_credits(shop["id"])),
        }

    def collect_credit(
        self,
        shop_query: str,
        customer: str,
        amount: Any,
        day: str = "",
    ) -> dict[str, Any]:
        """Collect customer credit payment: reduce credit and log a cash sale."""
        shop = self.require(shop_query)
        value = parse_amount(amount)
        if value <= 0:
            raise ValueError("amount must be positive")
        customer_norm = customer.strip()
        remaining = value
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM credits
                WHERE shop_id = ? AND lower(customer) = lower(?) AND amount > paid
                ORDER BY opened_on ASC, id ASC
                """,
                (shop["id"], customer_norm),
            ).fetchall()
            if not rows:
                raise ValueError(f"No open credit for customer {customer_norm!r}")
            for row in rows:
                due = float(row["amount"]) - float(row["paid"])
                pay = min(due, remaining)
                if pay <= 0:
                    continue
                conn.execute(
                    "UPDATE credits SET paid = paid + ?, updated_at = ? WHERE id = ?",
                    (pay, _utc_now(), row["id"]),
                )
                remaining = round(remaining - pay, 2)
                if remaining <= 0:
                    break
            if remaining > 0:
                raise ValueError(f"Collection exceeds outstanding credit by LKR {remaining}")

        cash = self.add_transaction(
            shop["id"],
            "sale",
            value,
            category="credit_collection",
            note=f"collected from {customer_norm}",
            day=day,
        )
        return {
            "collected": value,
            "customer": customer_norm,
            "cash_entry": cash["transaction"],
            "summary": cash["summary"],
            "credits": self.list_credits(shop["id"]),
            "aging": credit_aging(self.list_credits(shop["id"])),
        }

    def list_credits(self, shop_query: str) -> list[dict[str, Any]]:
        shop = self.require(shop_query)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM credits WHERE shop_id = ? ORDER BY opened_on ASC, id ASC",
                (shop["id"],),
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "shop_id": row["shop_id"],
                    "customer": row["customer"],
                    "amount": float(row["amount"]),
                    "paid": float(row["paid"]),
                    "outstanding": round(float(row["amount"]) - float(row["paid"]), 2),
                    "note": row["note"],
                    "opened_on": row["opened_on"],
                    "updated_at": row["updated_at"],
                }
                for row in rows
                if float(row["amount"]) - float(row["paid"]) > 0
            ]

    def daily_close(
        self,
        shop_query: str,
        till_count: Any,
        day: str = "",
        note: str = "",
    ) -> dict[str, Any]:
        shop = self.require(shop_query)
        day_iso = normalize_day(day.strip() or date.today().isoformat()).isoformat()
        till = parse_amount(till_count)
        ledger_balance = self.summary(shop["id"])["balance"]
        variance = round(till - ledger_balance, 2)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO daily_closes (shop_id, day, till_count, ledger_balance, variance, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(shop_id, day) DO UPDATE SET
                    till_count = excluded.till_count,
                    ledger_balance = excluded.ledger_balance,
                    variance = excluded.variance,
                    note = excluded.note,
                    created_at = excluded.created_at
                """,
                (shop["id"], day_iso, till, ledger_balance, variance, note.strip(), _utc_now()),
            )
        return {
            "shop": shop,
            "day": day_iso,
            "till_count": till,
            "ledger_balance": ledger_balance,
            "variance": variance,
            "matched": abs(variance) < 1,
            "note": note.strip(),
        }

    def last_daily_close(self, shop_query: str) -> dict[str, Any] | None:
        shop = self.require(shop_query)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM daily_closes WHERE shop_id = ? ORDER BY day DESC LIMIT 1",
                (shop["id"],),
            ).fetchone()
            if not row:
                return None
            return {
                "shop_id": row["shop_id"],
                "day": row["day"],
                "till_count": float(row["till_count"]),
                "ledger_balance": float(row["ledger_balance"]),
                "variance": float(row["variance"]),
                "note": row["note"],
                "created_at": row["created_at"],
            }

    def can_afford(self, shop_query: str, amount: Any, min_runway_days: int = 3) -> dict[str, Any]:
        summary = self.summary(shop_query)
        result = affordability(summary, amount, min_runway_days=min_runway_days)
        result["shop"] = summary["shop"]
        return result

    def dashboard(self, shop_query: str, window_days: int = 7) -> dict[str, Any]:
        shop = self.require(shop_query)
        summary = self.summary(shop["id"], window_days=window_days)
        inventory = self.list_inventory(shop["id"])
        credits = credit_aging(self.list_credits(shop["id"]))
        last_close = self.last_daily_close(shop["id"])
        alerts = build_alerts(summary=summary, inventory=inventory, credits=credits, last_close=last_close)
        return {
            "shop": shop,
            "summary": summary,
            "trends": self.trends(shop["id"], window_days=window_days),
            "inventory": inventory,
            "credits": credits,
            "last_daily_close": last_close,
            "alerts": alerts,
        }

    def import_csv(self, csv_path: str, shop_query: str = "") -> dict[str, Any]:
        path = Path(csv_path)
        if not path.is_file():
            raise ValueError(f"CSV not found: {csv_path}")

        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)

        if not rows:
            return {"imported": 0, "shop": None}

        shop_name = shop_query or (rows[0].get("shop_name") or rows[0].get("shop") or "Imported Shop")
        shop = self.find_shop(shop_name) or self.open_shop(
            name=str(shop_name),
            owner_name=str(rows[0].get("owner_name") or ""),
            category=str(rows[0].get("shop_category") or ""),
        )

        imported = 0
        for row in rows:
            kind = (row.get("kind") or row.get("type") or "").strip().lower()
            if kind in {"sale", "sales", "income", "revenue"}:
                kind = "sale"
            elif kind in {"expense", "expenses", "cost", "purchase"}:
                kind = "expense"
            else:
                continue
            amount = row.get("amount") or row.get("value")
            sku = str(row.get("sku") or "")
            qty_raw = row.get("quantity") or row.get("qty") or ""
            quantity = float(qty_raw) if str(qty_raw).strip() else None
            self.add_transaction(
                shop["id"],
                kind=kind,
                amount=amount,
                category=str(row.get("category") or ""),
                note=str(row.get("note") or row.get("description") or ""),
                day=str(row.get("day") or row.get("date") or ""),
                sku=sku,
                quantity=quantity,
            )
            imported += 1

        return {"imported": imported, "shop": shop, "summary": self.summary(shop["id"])}
