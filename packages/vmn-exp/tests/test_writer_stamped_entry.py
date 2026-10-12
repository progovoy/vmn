"""``stamped_entry`` makes a built entry (its ``type`` and fields) a log
entry like ``create_log_entry``'s: stamped now, the given entry untouched."""
from vmn_exp.core.writer import create_log_entry, stamped_entry


def test_a_stamped_entry_is_the_log_entry_create_log_entry_makes():
    built = {"type": "intent", "text": "try focal loss", "source": "user"}

    entry = stamped_entry(built)

    assert entry["timestamp"]
    assert entry == create_log_entry("intent", text="try focal loss", source="user",
                                     timestamp=entry["timestamp"])
    assert list(entry)[:2] == ["timestamp", "type"]
    assert built == {"type": "intent", "text": "try focal loss", "source": "user"}
