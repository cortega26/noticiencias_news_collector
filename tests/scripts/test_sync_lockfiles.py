import importlib.util
import sys
from pathlib import Path

_path = Path(__file__).resolve().parents[2] / "scripts" / "sync_lockfiles.py"
_spec = importlib.util.spec_from_file_location("sync_lockfiles_script", _path)
sl = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = sl
_spec.loader.exec_module(sl)


def test_upgrade_flags_go_before_the_input_file_and_default_to_none():
    args = ("-m", "piptools", "compile", "--output-file", "x.lock", "pyproject.toml")
    assert sl.build_compile_args(args) == args
    built = sl.build_compile_args(args, ["urllib3", "certifi==2026.7.22"])
    assert built[-1] == "pyproject.toml"
    assert built[:-5] == args[:-1]
    assert built[-5:-1] == (
        "--upgrade-package",
        "urllib3",
        "--upgrade-package",
        "certifi==2026.7.22",
    )


def test_every_lock_target_ends_with_the_input_file():
    for lockfile, args in sl.LOCK_TARGETS:
        assert args[-1] == "pyproject.toml", lockfile
        assert "--output-file" in args and lockfile in args


def test_cli_accepts_repeated_upgrade_package(monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["sync", "--upgrade-package", "a", "--upgrade-package", "b==1"]
    )
    assert sl.parse_args().upgrade_package == ["a", "b==1"]
    monkeypatch.setattr(sys, "argv", ["sync"])
    assert sl.parse_args().upgrade_package == []


def test_pinned_names_are_normalized_and_only_top_level_pins_count():
    text = (
        "foo-bar==1.0 \\\n    --hash=sha256:aa\n"
        "Some_Pkg==2 \\\n    # via x\n"
        "    indented==3\n"
        "# comment==4\n"
    )
    assert sl.pinned_names(text) == {"foo-bar", "some-pkg"}


def test_upgrade_packages_are_limited_to_locks_that_pin_them(tmp_path, monkeypatch):
    (tmp_path / "runtime.lock").write_text("urllib3==2.7.0 \\\n    --hash=sha256:aa\n")
    monkeypatch.setattr(sl, "ROOT_DIR", tmp_path)
    got = sl.upgrades_for_lock("runtime.lock", ["URLLIB3==2.8", "semgrep", "urllib3"])
    assert got == ["URLLIB3==2.8", "urllib3"]  # semgrep would be *added* -> excluded
    assert sl.upgrades_for_lock("missing.lock", ["urllib3"]) == []
