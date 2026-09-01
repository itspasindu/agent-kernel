from datetime import date, timedelta

from domain import (
    affordability,
    build_alerts,
    compare_windows,
    credit_aging,
    health_band,
    parse_amount,
    parse_quick_log,
    summarize_cashflow,
)


def _tx(kind: str, amount: float, days_ago: int = 0, category: str = "", note: str = ""):
    return {
        "kind": kind,
        "amount": amount,
        "category": category,
        "note": note,
        "day": (date.today() - timedelta(days=days_ago)).isoformat(),
    }


def test_parse_amount_strips_currency():
    assert parse_amount("LKR 2,400") == 2400.0
    assert parse_amount("Rs.1800") == 1800.0


def test_parse_quick_log_sale_and_expense():
    sale = parse_quick_log("Sold 12 buns 2400")
    assert sale["intent"] == "sale"
    assert sale["amount"] == 2400.0
    assert sale["quantity"] == 12.0
    expense = parse_quick_log("bought flour 1800")
    assert expense["intent"] == "expense"
    assert expense["amount"] == 1800.0


def test_parse_quick_log_credit():
    credit = parse_quick_log("credit Amara 500 bread")
    assert credit["intent"] == "credit_sale"
    assert credit["customer"] == "amara"
    assert credit["amount"] == 500.0
    paid = parse_quick_log("paid Amara 200")
    assert paid["intent"] == "credit_payment"
    assert paid["amount"] == 200.0


def test_healthy_band_with_buffer():
    txs = [
        _tx("sale", 10000, 1),
        _tx("expense", 1000, 1),
        _tx("sale", 10000, 0),
        _tx("expense", 1000, 0),
    ]
    summary = summarize_cashflow(txs, window_days=7)
    assert summary["balance"] == 18000.0
    assert summary["band"] == "HEALTHY"
    assert summary["runway_days"] >= 7


def test_critical_when_balance_negative():
    txs = [_tx("expense", 5000, 0), _tx("sale", 1000, 0)]
    summary = summarize_cashflow(txs, window_days=7)
    assert summary["balance"] == -4000.0
    assert summary["band"] == "CRITICAL"


def test_tight_when_runway_under_seven():
    band = health_band(balance=3000, runway_days=4, net_daily=100)
    assert band == "TIGHT"


def test_affordability_blocks_unsafe_buy():
    summary = summarize_cashflow([_tx("sale", 5000, 0), _tx("expense", 1000, 0)], window_days=7)
    result = affordability(summary, 4500, min_runway_days=3)
    assert result["safe"] is False


def test_credit_aging_marks_overdue():
    aged = credit_aging(
        [
            {
                "customer": "Amara",
                "outstanding": 500,
                "opened_on": (date.today() - timedelta(days=10)).isoformat(),
                "note": "bread",
            }
        ]
    )
    assert aged[0]["overdue"] is True
    assert aged[0]["age_days"] == 10


def test_alerts_include_low_stock_and_credit():
    summary = summarize_cashflow([_tx("sale", 2000, 0), _tx("expense", 1500, 0)], window_days=7)
    alerts = build_alerts(
        summary=summary,
        inventory=[{"sku": "flour", "quantity": 1, "reorder_level": 3}],
        credits=[{"customer": "Amara", "outstanding": 500, "overdue": True}],
    )
    codes = {row["code"] for row in alerts}
    assert "low-stock" in codes
    assert "credit-overdue" in codes


def test_compare_windows_reports_change():
    txs = [
        _tx("sale", 1000, 10),
        _tx("sale", 3000, 1),
        _tx("expense", 500, 1),
    ]
    trend = compare_windows(txs, window_days=7)
    assert trend["sales"]["current"] >= trend["sales"]["previous"]
