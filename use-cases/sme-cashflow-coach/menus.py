"""WhatsApp interactive menus for SME Cashflow Coach."""

from __future__ import annotations

# Maps interactive list row IDs to agent prompts.
MENU_PROMPTS: dict[str, str] = {
    "menu_summary": "Show my cash summary, balance, runway days, and HEALTHY/TIGHT/CRITICAL band.",
    "menu_dashboard": "Show my full dashboard with alerts, trends, stock, and customer credit.",
    "menu_advice": "What should I do next for my shop cash and credit?",
    "menu_trends": "Compare this week versus last week for sales and expenses.",
    "menu_stock": "List my inventory and flag any low-stock items.",
    "menu_credits": "List open customer credit with aging. Who owes me money?",
    "menu_how_log": (
        "Explain briefly how I should log sales, expenses, customer credit, and collections "
        "in WhatsApp. Use examples: sold 12 buns 2400 | bought flour 1800 | credit Amara 500 bread | paid Amara 200"
    ),
}

MENU_TRIGGERS = {
    "menu",
    "/menu",
    "help",
    "/help",
    "start",
    "/start",
    "hi",
    "hello",
    "options",
}


def is_menu_trigger(text: str) -> bool:
    return text.strip().lower() in MENU_TRIGGERS


def prompt_for_menu_id(row_id: str) -> str | None:
    return MENU_PROMPTS.get(row_id)


def main_menu_payload(to_number: str) -> dict:
    """WhatsApp Cloud API interactive list payload."""
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": "SME Cashflow Coach"},
            "body": {
                "text": (
                    "Choose an action below, or type freely.\n"
                    "Examples: sold 12 buns 2400 | credit Amara 500 | paid Amara 200"
                )
            },
            "footer": {"text": "Reply menu anytime to open this again"},
            "action": {
                "button": "Open menu",
                "sections": [
                    {
                        "title": "Cash & advice",
                        "rows": [
                            {
                                "id": "menu_summary",
                                "title": "Cash summary",
                                "description": "Balance, runway, health band",
                            },
                            {
                                "id": "menu_dashboard",
                                "title": "Full dashboard",
                                "description": "Alerts, trends, stock, credit",
                            },
                            {
                                "id": "menu_advice",
                                "title": "What should I do?",
                                "description": "Top next actions for today",
                            },
                            {
                                "id": "menu_trends",
                                "title": "Week trends",
                                "description": "This week vs last week",
                            },
                        ],
                    },
                    {
                        "title": "Stock & credit",
                        "rows": [
                            {
                                "id": "menu_stock",
                                "title": "Inventory",
                                "description": "Stock levels and low stock",
                            },
                            {
                                "id": "menu_credits",
                                "title": "Customer credit",
                                "description": "Who owes the shop",
                            },
                            {
                                "id": "menu_how_log",
                                "title": "How to log",
                                "description": "Sale, expense, credit examples",
                            },
                        ],
                    },
                ],
            },
        },
    }


def quick_reply_buttons_payload(to_number: str) -> dict:
    """Compact 3-button menu for fast follow-ups."""
    return {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to_number,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": "Quick actions:"},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": "menu_summary", "title": "Cash summary"}},
                    {"type": "reply", "reply": {"id": "menu_advice", "title": "Advice"}},
                    {"type": "reply", "reply": {"id": "menu_credits", "title": "Credit list"}},
                ]
            },
        },
    }
