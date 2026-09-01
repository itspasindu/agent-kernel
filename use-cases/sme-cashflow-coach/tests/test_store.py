from datetime import date, timedelta
from pathlib import Path

from store import ShopStore


def test_open_shop_log_and_summary(tmp_path: Path):
    store = ShopStore(tmp_path / "shop.db")
    shop = store.open_shop(name="Nimal Bakery", owner_name="Nimal", category="bakery")
    store.add_transaction(shop["id"], "sale", "2400", note="12 buns")
    store.add_transaction(shop["id"], "expense", "1800", note="flour", category="flour")
    summary = store.summary(shop["id"])
    assert summary["balance"] == 600.0
    assert summary["shop"]["name"] == "Nimal Bakery"
    assert summary["transaction_count"] == 2


def test_import_example_csv(tmp_path: Path):
    store = ShopStore(tmp_path / "shop.db")
    csv_path = Path(__file__).resolve().parents[1] / "data" / "ledger.example.csv"
    result = store.import_csv(str(csv_path))
    assert result["imported"] >= 10
    assert result["summary"]["transaction_count"] == result["imported"]
    assert result["shop"]["name"] == "Nimal Bakery"


def test_inventory_credit_close_and_dashboard(tmp_path: Path):
    store = ShopStore(tmp_path / "shop.db")
    shop = store.open_shop(name="Pasindu Bakery", owner_name="Pasindu", category="bakery")
    store.set_stock(shop["id"], sku="flour", quantity=2, reorder_level=5, unit="kg")
    store.add_transaction(shop["id"], "sale", "3000", note="buns", category="buns")
    store.add_credit(shop["id"], "Amara", 500, note="bread")
    # backdate credit to make it overdue
    with store._connect() as conn:
        old = (date.today() - timedelta(days=9)).isoformat()
        conn.execute("UPDATE credits SET opened_on = ? WHERE shop_id = ?", (old, shop["id"]))
    store.daily_close(shop["id"], till_count=2500)
    dash = store.dashboard(shop["id"])
    assert dash["summary"]["balance"] == 3000.0
    assert any(item["sku"] == "flour" and item["low_stock"] for item in dash["inventory"])
    assert any(row["customer"] == "Amara" and row["overdue"] for row in dash["credits"])
    assert any(alert["code"] == "credit-overdue" for alert in dash["alerts"])
    assert dash["last_daily_close"]["variance"] == -500.0


def test_collect_credit_increases_cash(tmp_path: Path):
    store = ShopStore(tmp_path / "shop.db")
    shop = store.open_shop(name="Corner Shop")
    store.add_credit(shop["id"], "Saman", 1000)
    result = store.collect_credit(shop["id"], "Saman", 400)
    assert result["collected"] == 400.0
    assert store.summary(shop["id"])["balance"] == 400.0
    assert store.list_credits(shop["id"])[0]["outstanding"] == 600.0


def test_can_afford(tmp_path: Path):
    store = ShopStore(tmp_path / "shop.db")
    shop = store.open_shop(name="Tea Kiosk")
    store.add_transaction(shop["id"], "sale", "10000")
    store.add_transaction(shop["id"], "expense", "1000")
    assert store.can_afford(shop["id"], 2000)["safe"] is True
