from menus import is_menu_trigger, main_menu_payload, prompt_for_menu_id


def test_menu_triggers():
    assert is_menu_trigger("menu")
    assert is_menu_trigger("/help")
    assert not is_menu_trigger("sold 12 buns 2400")


def test_menu_prompt_mapping():
    assert "runway" in prompt_for_menu_id("menu_summary").lower()
    assert "credit" in prompt_for_menu_id("menu_credits").lower()


def test_main_menu_payload_shape():
    payload = main_menu_payload("94770000000")
    assert payload["type"] == "interactive"
    assert payload["interactive"]["type"] == "list"
    rows = []
    for section in payload["interactive"]["action"]["sections"]:
        rows.extend(section["rows"])
    assert len(rows) <= 10
    assert any(row["id"] == "menu_dashboard" for row in rows)
