"""Persistence, env-override parsing and CLI of ``noticiencias.config_manager``.

Real temp files, no mocks: these functions write the sealed config contract and the
.env holding secrets, so a regression here is silent data loss or a leaked value.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

import pytest
from noticiencias import config_manager as cm


@pytest.fixture(autouse=True)
def _isolated_config_environment(tmp_path, monkeypatch):
    """No ambient override (process env, repo-root .env) may leak into these tests."""
    for name in list(os.environ):
        if name.startswith("NOTICIENCIAS__") or name in cm._legacy_env_key_map():
            monkeypatch.delenv(name)
    monkeypatch.setattr(
        cm,
        "_default_paths",
        lambda: (tmp_path / "no-default.toml", tmp_path / "no-default.env"),
    )


TIMEOUT_PATH = "collection.request_timeout_seconds"
TIMEOUT_ENV = "NOTICIENCIAS__COLLECTION__REQUEST_TIMEOUT_SECONDS"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  ", ""),
        ("TRUE", True),
        ("false", False),
        ("None", None),
        ("null", None),
        ("42", 42),
        ("-7", -7),
        ("3.5", 3.5),
        ('["a", 1]', ["a", 1]),
        ('{"k": 2}', {"k": 2}),
        ("[not json]", "[not json]"),
        ("plain text", "plain text"),
    ],
)
def test_coerce_text(raw, expected):
    assert cm._coerce_text(raw) == expected


def test_parse_kv_override_builds_dotted_lowercase_path():
    assert cm._parse_kv_override(TIMEOUT_ENV, "20", "NOTICIENCIAS") == (
        TIMEOUT_PATH,
        20,
    )


@pytest.mark.parametrize("bad", ["OTHER__A__B", "NOTICIENCIAS__", "NOTICIENCIAS____"])
def test_parse_kv_override_rejects_foreign_or_empty_keys(bad):
    with pytest.raises(cm.ConfigError):
        cm._parse_kv_override(bad, "1", "NOTICIENCIAS")


def test_assign_path_creates_intermediate_tables_and_replaces_scalars():
    target = {"a": 1}
    cm._assign_path(target, "a.b.c", 5)
    cm._assign_path(target, "x", 2)
    assert target == {"a": {"b": {"c": 5}}, "x": 2}


def test_serialize_for_toml_drops_none_and_normalizes_types():
    out = cm._serialize_for_toml(
        {
            "p": Path("/tmp/x"),
            "n": None,
            "t": (1, None, 2),
            "l": [None, "a"],
            "m": {"z": None},
        }
    )
    assert out == {"p": "/tmp/x", "t": [1, 2], "l": ["a"], "m": {}}


def test_fallback_toml_encoder_round_trips_through_tomllib():
    data = {
        "top": 1,
        "flag": True,
        "name": 'with "quotes"',
        "empty": None,
        "items": [1, 2, "x"],
        "section": {"ratio": 0.5, "inner": {"k": "v"}},
    }
    parsed = tomllib.loads(cm._encode_toml(data))
    assert parsed["top"] == 1 and parsed["flag"] is True
    assert parsed["name"] == 'with "quotes"' and parsed["empty"] == ""
    assert parsed["items"] == [1, 2, "x"]
    assert parsed["section"] == {"ratio": 0.5, "inner": {"k": "v"}}


def test_load_toml_missing_file_is_empty_and_invalid_raises(tmp_path):
    assert cm._load_toml(tmp_path / "nope.toml") == {}
    bad = tmp_path / "bad.toml"
    bad.write_text("[unclosed", encoding="utf-8")
    with pytest.raises(cm.ConfigError, match="Failed to parse"):
        cm._load_toml(bad)


# ------------------------------------------------------------------ .env files


def test_env_overrides_round_trip_with_quoting_and_removal(tmp_path):
    env = tmp_path / ".env"
    cm.save_env_overrides(
        {"A": "1", "SPACED": "two words", "HASHED": "a#b", "EMPTY_DROPPED": ""}, env
    )
    text = env.read_text(encoding="utf-8")
    assert "A=1" in text and 'SPACED="two words"' in text and 'HASHED="a#b"' in text
    assert "EMPTY_DROPPED" not in text
    assert cm.load_env_overrides(env) == {
        "A": "1",
        "SPACED": "two words",
        "HASHED": "a#b",
    }

    cm.save_env_overrides({"A": None, "B": "2", "SPACED": ""}, env)
    assert cm.load_env_overrides(env) == {"HASHED": "a#b", "B": "2"}
    assert not list(tmp_path.glob(".*.tmp"))  # atomic write leaves no temp file


def test_load_env_overrides_missing_file_is_empty(tmp_path):
    assert cm.load_env_overrides(tmp_path / "absent.env") == {}


def test_format_env_assignment():
    assert cm._format_env_assignment("K", "") == 'K=""'
    assert cm._format_env_assignment("K", "v") == "K=v"
    assert cm._format_env_assignment("K", "a b") == 'K="a b"'


# ----------------------------------------------------------------- load/save


def _write(tmp_path, body=""):
    path = tmp_path / "config.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_save_config_round_trips_and_backs_up_previous_file(tmp_path):
    path = _write(tmp_path, f"[collection]\nrequest_timeout_seconds = 15\n")
    config = cm.load_config(path, environ={})
    updated = cm._apply_updates(config, {TIMEOUT_PATH: "30"})
    assert cm.save_config(updated, path) == path
    assert cm.load_config(path, environ={}).collection.request_timeout_seconds == 30
    backups = list((tmp_path / cm.BACKUP_DIRNAME).glob("config.toml.*.bak"))
    assert len(backups) == 1
    assert "request_timeout_seconds = 15" in backups[0].read_text(encoding="utf-8")
    assert not list(tmp_path.glob(".noticiencias-config-*"))  # no stray temp file


def test_save_config_creates_parent_dirs_for_new_file(tmp_path):
    target = tmp_path / "nested" / "dir" / "config.toml"
    cm.save_config(cm.load_config(_write(tmp_path), environ={}), target)
    assert target.exists() and not (target.parent / cm.BACKUP_DIRNAME).exists()


def test_load_config_reports_invalid_values_with_their_origin(tmp_path):
    path = _write(tmp_path, "[collection]\nrequest_timeout_seconds = 'abc'\n")
    with pytest.raises(cm.ConfigError) as err:
        cm.load_config(path, environ={})
    assert "request_timeout_seconds" in str(err.value)


def test_legacy_flat_env_key_is_shadowed_by_canonical_one_with_warning(tmp_path):
    path = _write(tmp_path)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    environ = {
        "NOTICIENCIAS__GITHUB__USER_NAME": "canonical",
        "GITHUB_USER_NAME": "legacy",
        "OLLAMA_MODEL": "llama-x",
    }
    config = cm.load_config(path, environ=environ)
    assert config.github.user_name == "canonical"
    assert config.ollama.model == "llama-x"  # unshadowed legacy key still applies
    codes = [w.code for w in config._metadata.warnings]
    assert "legacy_env_shadowed" in codes


def test_unsupported_legacy_refinery_env_file_is_reported(tmp_path):
    path = _write(tmp_path)
    (tmp_path / ".env").write_text("SHARED=root\n", encoding="utf-8")
    legacy = tmp_path / "apps" / "refinery"
    legacy.mkdir(parents=True)
    (legacy / ".env").write_text("SHARED=legacy\n", encoding="utf-8")
    config = cm.load_config(path, environ={})
    warning = next(
        w for w in config._metadata.warnings if w.code == "legacy_env_file_ignored"
    )
    assert warning.keys == ("SHARED",) and "legacy" in warning.render().lower()


# ------------------------------------------------------ helpers used by the CLI


def test_diff_configs_masks_secret_values():
    before = {"github": {"token": "old-secret", "user_name": "a"}, "n": 1}
    after = {"github": {"token": "new-secret", "user_name": "b"}, "n": 1}
    lines = cm._diff_configs(before, after)
    assert lines == [
        "github.token: ***masked*** -> ***masked***",
        'github.user_name: "a" -> "b"',
    ]
    assert all("secret" not in line for line in lines)


def test_apply_updates_rejects_unknown_keys_and_invalid_values(tmp_path):
    config = cm.load_config(_write(tmp_path), environ={})
    with pytest.raises(cm.ConfigError, match="Unknown configuration key"):
        cm._apply_updates(config, {"nope": "1"})
    with pytest.raises(cm.ConfigError, match="Unknown configuration key"):
        cm._apply_updates(config, {"nope.child": "1"})
    with pytest.raises(cm.ConfigError):
        cm._apply_updates(config, {TIMEOUT_PATH: "not-a-number"})
    assert config.collection.request_timeout_seconds != "not-a-number"


def test_apply_updates_marks_provenance_as_cli(tmp_path):
    config = cm.load_config(_write(tmp_path), environ={})
    updated = cm._apply_updates(config, {TIMEOUT_PATH: "44"})
    assert updated.collection.request_timeout_seconds == 44
    assert updated._metadata.provenance[TIMEOUT_PATH].layer == "cli"


def test_explain_masks_secrets_and_rejects_unknown_key(tmp_path):
    config = cm.load_config(
        _write(tmp_path, "[github]\ntoken = 'ZZ-secret-value'\n"), environ={}
    )
    text = cm._explain(config, "github.token")
    assert "ZZ-secret-value" not in text and "***masked***" in text
    assert "source: file" in text
    with pytest.raises(cm.ConfigError, match="Unknown configuration key"):
        cm._explain(config, "no.such.key")


def test_resolve_and_safe_repr():
    assert cm._resolve_value({"a": {"b": 3}}, "a.b") == 3
    with pytest.raises(cm.ConfigError):
        cm._resolve_value({"a": 1}, "a.b")
    assert cm._safe_repr(Path("/x")) == "/x"
    assert cm._safe_repr({1, 2}).startswith("{")  # not JSON serializable -> repr


# ------------------------------------------------------------------------ CLI


def _run(capsys, *args):
    rc = cm.main(list(args))
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


def test_cli_validate_and_show_sources(tmp_path, capsys):
    path = _write(tmp_path, "[collection]\nrequest_timeout_seconds = 15\n")
    rc, out, _ = _run(capsys, "--config", str(path), "--validate")
    assert (rc, out.strip()) == (0, "Configuration OK")
    rc, out, _ = _run(capsys, "--config", str(path), "--show-sources")
    assert rc == 0 and out.startswith("Active configuration sources:")


def test_cli_dump_defaults_is_valid_toml_and_schema_is_a_table(capsys):
    rc, out, _ = _run(capsys, "--dump-defaults")
    assert rc == 0 and isinstance(tomllib.loads(out), dict)
    rc, out, _ = _run(capsys, "--print-schema")
    assert rc == 0 and out.startswith("| Field | Type |") and TIMEOUT_PATH in out


def test_cli_explain_known_and_unknown_key(tmp_path, capsys):
    path = _write(tmp_path)
    rc, out, _ = _run(capsys, "--config", str(path), "--explain", TIMEOUT_PATH)
    assert rc == 0 and out.startswith(f"{TIMEOUT_PATH} = ") and "source:" in out
    rc, _, err = _run(capsys, "--config", str(path), "--explain", "no.such")
    assert rc == 1 and err.startswith("error: Unknown configuration key")


def test_cli_set_persists_prints_diff_and_masks_secrets(tmp_path, capsys):
    path = _write(tmp_path, "[collection]\nrequest_timeout_seconds = 15\n")
    rc, out, _ = _run(
        capsys,
        "--config",
        str(path),
        "--set",
        f"{TIMEOUT_PATH}=31",
        "github.token=sup3r",
    )
    assert rc == 0
    assert (
        f"{TIMEOUT_PATH}: 15 -> 31" in out and f"Saved configuration to {path}" in out
    )
    assert "sup3r" not in out and "github.token: ***masked***" in out
    saved = cm.load_config(path, environ={})
    assert saved.collection.request_timeout_seconds == 31
    assert saved.github.token == "sup3r"


@pytest.mark.parametrize(
    "args",
    [
        ("--set", "missing-equals"),
        ("--set", "nope.key=1"),
        ("--set", f"{TIMEOUT_PATH}=not-a-number"),
    ],
)
def test_cli_set_errors_return_1_without_touching_the_file(tmp_path, capsys, args):
    path = _write(tmp_path, "[collection]\nrequest_timeout_seconds = 15\n")
    before = path.read_text(encoding="utf-8")
    rc, _, err = _run(capsys, "--config", str(path), *args)
    assert rc == 1 and err.startswith("error:")
    assert path.read_text(encoding="utf-8") == before


def test_cli_invalid_config_returns_1(tmp_path, capsys):
    path = _write(tmp_path, "[collection]\nrequest_timeout_seconds = 'x'\n")
    rc, _, err = _run(capsys, "--config", str(path), "--validate")
    assert rc == 1 and "request_timeout_seconds" in err


def test_default_repo_paths_are_never_consulted_by_the_suite(tmp_path):
    assert cm.default_config_path().name == "no-default.toml"
    assert cm.default_env_path().name == "no-default.env"
