from datetime import datetime

from hadar_tracker.util import now_iso


def test_now_iso_is_parseable_iso8601():
    value = now_iso()
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
