"""Plan 134 back-compat shim — this module now lives under ``news_collector``.

The deployed serving image (``Dockerfile.serving``) ships no ``apps/`` tree, so
the canonical home is ``news_collector.serving.analytics_read_model``. This file
keeps the legacy Streamlit import path — and the tests that patch through it —
working by aliasing the canonical module into ``sys.modules``: both import paths
resolve to the *same* module object, so ``monkeypatch.setattr`` on either path
behaves exactly as it did before the move.
"""

import sys

from news_collector.serving import analytics_read_model as _canonical

sys.modules[__name__] = _canonical
