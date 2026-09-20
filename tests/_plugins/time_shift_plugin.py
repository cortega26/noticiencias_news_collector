"""pytest plugin: run every test with the clock moved forward.

Used by ``make test-timeshift`` to expose tests that silently depend on
"today" (hard-coded dates compared against now). Days come from
``TIME_SHIFT_DAYS`` (default 120). Requires ``time-machine``. Tests that model
real expiry (e.g. the pip-audit allowlist) are expected to fail when the shift
crosses an expiry date.
"""

import datetime as _dt
import os

import pytest
import time_machine


@pytest.fixture(autouse=True)
def _shift_clock():
    days = float(os.environ.get("TIME_SHIFT_DAYS", "120"))
    target = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=days)
    with time_machine.travel(target, tick=True):
        yield
