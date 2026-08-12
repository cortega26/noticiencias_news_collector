"""Characterization tests for the automatic weight-rebalancing UI in the
Refinery admin panel (settings tab, `apps/refinery/admin_panel.py`).

Regression for the scoring-weights save bug: editing one weight slider left
the sum of the four weights away from 1.0, which
``config_settings.validate_config()`` rejects, so save_toml_config()
silently no-oped and config.toml kept the old weights.

The app now seeds four persistent widget keys (``w_*``) from the loaded
config, and each slider's ``on_change`` handler rebalances the other three
proportionally so the total returns to 1.0 before the script re-runs. This
suite drives the REAL app through AppTest (same harness as
test_admin_panel_characterization.py) and asserts the visible widget state
after the interaction, not just the pure helper.

These tests run only under the isolated `.venv-refinery` environment
(``make test-refinery``) — the main `.venv` has no streamlit installed.
"""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

ADMIN_PANEL = "apps/refinery/admin_panel.py"

WEIGHT_KEYS = (
    "w_source_credibility",
    "w_recency",
    "w_content_quality",
    "w_engagement_potential",
)


def _weight_sliders(at: AppTest) -> dict[str, float]:
    """Return the current value of the four weight sliders, keyed by widget key."""
    return {
        s.key: float(s.value)
        for s in at.slider
        if s.key is not None and s.key in WEIGHT_KEYS
    }


def test_weight_sliders_render_from_config():
    at = AppTest.from_file(ADMIN_PANEL)
    at.run(timeout=60)

    assert not at.exception, [str(e) for e in at.exception]
    values = _weight_sliders(at)
    assert set(values) == set(WEIGHT_KEYS)
    # Seeded from config.toml; the four must be present and sum to ~1.0.
    assert round(sum(values.values()), 4) == 1.0


def test_moving_one_weight_automatically_rebalances_siblings():
    """The core regression: moving one slider (e.g. recency 0.1 -> 0.5) must
    rescale the other three so the total stays 1.0 with no exception."""
    at = AppTest.from_file(ADMIN_PANEL)
    at.run(timeout=60)
    assert not at.exception

    recency = next(s for s in at.slider if s.key == "w_recency")
    recency.set_value(0.5)
    at.run(timeout=60)

    assert not at.exception, [str(e) for e in at.exception]
    values = _weight_sliders(at)
    assert set(values) == set(WEIGHT_KEYS)
    assert values["w_recency"] == 0.5
    assert round(sum(values.values()), 4) == 1.0
    # The moved weight grew, so the siblings must have shrunk, not kept
    # their original values (that is what the old bug did and then validate
    # rejected the save).
    assert values["w_source_credibility"] < 0.1
    assert values["w_content_quality"] < 0.4
    assert values["w_engagement_potential"] < 0.4


def test_moving_last_slider_rebalances_already_renderered_siblings():
    """Regression guard for the Streamlit ordering trap: the handler's
    session_state writes must not try to mutate a widget that was already
    instantiated in the same run (that raises), which forced the buggy path
    of leaving sibling sliders at their old values."""
    at = AppTest.from_file(ADMIN_PANEL)
    at.run(timeout=60)
    assert not at.exception

    engagement = next(s for s in at.slider if s.key == "w_engagement_potential")
    engagement.set_value(0.5)
    at.run(timeout=60)

    assert not at.exception, [str(e) for e in at.exception]
    values = _weight_sliders(at)
    assert values["w_engagement_potential"] == 0.5
    assert round(sum(values.values()), 4) == 1.0
    assert values["w_source_credibility"] < 0.1
    assert values["w_recency"] < 0.1
    assert values["w_content_quality"] < 0.4


def test_rebalanced_weights_are_what_the_save_button_would_persist():
    """The visible sliders after a move must satisfy validate_config(), i.e.
    the same values the 'Guardar Config Colector' button submits via
    save_toml_config() would pass the cross-field sum-to-1.0 business rule."""
    from noticiencias.config_manager import Config, load_config

    from news_collector.config.settings import validate_config

    at = AppTest.from_file(ADMIN_PANEL)
    at.run(timeout=60)
    assert not at.exception

    recency = next(s for s in at.slider if s.key == "w_recency")
    recency.set_value(0.5)
    at.run(timeout=60)
    assert not at.exception

    values = _weight_sliders(at)
    payload = load_config().model_dump(mode="python")
    payload["scoring"]["weights"] = {k[2:]: v for k, v in values.items()}
    # validate_config raises ConfigError if the sum drifts; that is the
    # exact rejection that made saves no-op before the fix.
    validate_config(Config.model_validate(payload))
