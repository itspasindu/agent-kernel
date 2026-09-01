from dedupe import RecentMessageIds


def test_message_id_dedupe_blocks_repeats():
    seen = RecentMessageIds(ttl_seconds=60, max_size=10)
    assert seen.seen_or_add("wamid.A") is False
    assert seen.seen_or_add("wamid.A") is True
    assert seen.seen_or_add("wamid.B") is False
