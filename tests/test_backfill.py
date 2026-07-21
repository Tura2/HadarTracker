import logging

from hadar_tracker import backfill


def test_run_backfill_returns_not_implemented_code():
    assert backfill.run_backfill() == backfill.NOT_IMPLEMENTED_EXIT_CODE
    assert backfill.NOT_IMPLEMENTED_EXIT_CODE == 2


def test_run_backfill_logs_undetermined_message(caplog):
    with caplog.at_level(logging.WARNING):
        backfill.run_backfill()
    assert any("mechanism" in r.message.lower() for r in caplog.records)
