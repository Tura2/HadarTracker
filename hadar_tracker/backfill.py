from __future__ import annotations

import logging
import sys

# Distinct from success (0) and the check job's runtime-error code (1): the
# backfill mechanism is simply not built yet.
NOT_IMPLEMENTED_EXIT_CODE = 2

_MESSAGE = (
    "Historical backfill is not implemented: the discovery mechanism is "
    "undetermined. The live stream endpoint "
    "(HD_STREAM_FORUM_USER_MESSAGES.ashx) only covers ~1 day of activity, not "
    "Hadar's full archive. A follow-up investigation is required (does the `m` "
    "parameter accept a cursor/offset? is there a separate paginated per-user "
    "history endpoint?) before this can be built. Not required for Phase 1 "
    "launch; required before Phase 2. See "
    "docs/superpowers/specs/2026-07-21-phase1-tracker-design.md, 'Open items'."
)


def run_backfill() -> int:
    """Report that backfill is undetermined and exit informatively.

    Deliberately does NOT touch the network or the database — there is no
    mechanism to implement yet, and pretending otherwise would be a silent
    no-op. Returns NOT_IMPLEMENTED_EXIT_CODE.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger("hadar_tracker.backfill").warning(_MESSAGE)
    return NOT_IMPLEMENTED_EXIT_CODE


def main() -> None:
    sys.exit(run_backfill())


if __name__ == "__main__":
    main()
