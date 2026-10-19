import importlib.util
import json
import sys
from pathlib import Path


def _load_script():
    path = Path(__file__).resolve().parents[3] / "scripts" / "test_suite_audit.py"
    spec = importlib.util.spec_from_file_location("suite_audit_script", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses need the module registered
    spec.loader.exec_module(module)
    return module


sa = _load_script()


def _cov(tmp_path, files, contexts=None):
    payload = {"files": {}}
    for name, (stmts, cov, br, cbr) in files.items():
        payload["files"][name] = {
            "summary": {
                "num_statements": stmts,
                "covered_lines": cov,
                "num_branches": br,
                "covered_branches": cbr,
            },
            "contexts": (contexts or {}).get(name, {}),
        }
    path = tmp_path / "cov.json"
    path.write_text(json.dumps(payload))
    return path


def test_load_and_rank_gaps(tmp_path):
    path = _cov(
        tmp_path,
        {
            "news_collector/a/big.py": (200, 100, 20, 5),
            "news_collector/a/small.py": (10, 0, 0, 0),
            "news_collector/b/ok.py": (100, 95, 10, 9),
        },
    )
    files = sa.load_coverage(path)
    gaps = sa.critical_gaps(files, min_statements=40, threshold=85)
    assert [g.path for g in gaps] == ["news_collector/a/big.py"]  # small.py < min
    assert gaps[0].missing == 100 and gaps[0].line_rate == 50.0
    tot = sa.totals(files.values())
    assert (tot.statements, tot.covered) == (310, 195)
    assert round(tot.branch_rate, 1) == 46.7


def test_package_summary_is_worst_first(tmp_path):
    files = sa.load_coverage(
        _cov(
            tmp_path,
            {
                "news_collector/a/x.py": (10, 10, 0, 0),
                "news_collector/b/y.py": (10, 2, 0, 0),
            },
        )
    )
    names = [p.name for p in sa.summarize_packages(files)]
    assert names == ["news_collector/b", "news_collector/a"]


def test_tests_touching_no_code(tmp_path):
    path = _cov(
        tmp_path,
        {"news_collector/a.py": (5, 5, 0, 0)},
        {
            "news_collector/a.py": {
                "1": ["tests/t.py::test_real|run"],
                "2": ["tests/t.py::test_param[1]|run", ""],
            }
        },
    )
    seen = sa.contexts_by_test(path)
    collected = [
        "tests/t.py::test_real",
        "tests/t.py::test_param[1]",
        "tests/t.py::test_param[2]",
        "tests/t.py::test_spike",
    ]
    assert sa.tests_touching_no_code(collected, seen) == ["tests/t.py::test_spike"]


def test_test_quality_finds_assertionless_and_mock_heavy(tmp_path):
    tdir = tmp_path / "tests"
    tdir.mkdir()
    (tdir / "test_a.py").write_text(
        "import pytest\n"
        "@pytest.fixture\n"
        "def test_db_manager():\n    return 1\n"
        "def test_empty():\n    x = 1\n"
        "def test_assert():\n    assert 1\n"
        "def test_raises():\n    with pytest.raises(ValueError):\n        int('x')\n"
        "def test_mock_assert(m):\n    m.assert_called_once()\n"
    )
    (tdir / "test_b.py").write_text(
        "from unittest.mock import MagicMock, patch\n"
        "def test_x():\n    a = MagicMock(); b = MagicMock(); c = MagicMock()\n"
        "    with patch('x'), patch('y'), patch('z'):\n        assert a\n"
    )
    q = sa.analyze_test_quality(tdir, mock_ratio=5)
    assert q.total_tests == 5  # the fixture is not counted
    assert q.no_assertion == [f"{tdir / 'test_a.py'}::test_empty"]
    assert [d["file"] for d in q.mock_heavy] == [str(tdir / "test_b.py")]


def test_render_markdown_sections(tmp_path):
    files = sa.load_coverage(
        _cov(tmp_path, {"news_collector/a/x.py": (100, 50, 10, 5)})
    )
    q = sa.TestQuality(no_assertion=["t::a"], mock_heavy=[], total_tests=3)
    md = sa.render_markdown(files, q, ["tests/t.py::test_spike"])
    assert "50.0 %" in md and "news_collector/a/x.py" in md
    assert "t::a" in md and "tests/t.py::test_spike" in md and "- ninguno" in md


def test_script_writes_reports(tmp_path):
    path = _cov(tmp_path, {"news_collector/a/x.py": (100, 90, 0, 0)})
    collected = tmp_path / "collected.txt"
    collected.write_text("tests/t.py::test_a\n\n===== 1 test collected =====\n")
    tdir = tmp_path / "tests"
    tdir.mkdir()
    (tdir / "test_z.py").write_text("def test_z():\n    assert True\n")
    mod = sa
    out = tmp_path / "out"
    rc = mod.main(
        [
            "--coverage",
            str(path),
            "--collected",
            str(collected),
            "--tests",
            str(tdir),
            "--out",
            str(out),
        ]
    )
    assert rc == 0
    data = json.loads((out / "test_audit.json").read_text())
    assert data["line_rate"] == 90.0
    assert data["tests_touching_no_code"] == ["tests/t.py::test_a"]
    assert (out / "test_audit.md").read_text().startswith("# Auditoría")


def test_static_mode_writes_reduced_report(tmp_path):
    tdir = tmp_path / "tests"
    tdir.mkdir()
    (tdir / "test_s.py").write_text(
        "def test_ok():\n    assert 1\n" "def test_weak():\n    print('hi')\n"
    )
    out = tmp_path / "out"

    rc = sa.main(["--static-only", "--tests", str(tdir), "--out", str(out)])

    assert rc == 0
    data = json.loads((out / "test_audit.json").read_text())
    assert data["total_tests"] == 2
    assert data["no_assertion"] == [f"{tdir / 'test_s.py'}::test_weak"]
    assert "line_rate" not in data and "tests_touching_no_code" not in data
    assert "Tests sin aserción" in (out / "test_audit.md").read_text()


def test_baseline_gate_blocks_growth_and_allows_shrink(tmp_path, capsys):
    tdir = tmp_path / "tests"
    tdir.mkdir()
    weak = tdir / "test_s.py"
    weak.write_text("def test_weak():\n    print('hi')\n")
    out = tmp_path / "out"
    baseline = tmp_path / "baseline.json"

    rc = sa.main(
        [
            "--static-only",
            "--tests",
            str(tdir),
            "--out",
            str(out),
            "--write-baseline",
            str(baseline),
        ]
    )
    assert rc == 0
    assert json.loads(baseline.read_text()) == {"no_assertion": [f"{weak}::test_weak"]}

    # Fixing a test shrinks the list and needs no baseline refresh.
    weak.write_text("def test_weak():\n    assert True\n")
    rc = sa.main(
        [
            "--static-only",
            "--tests",
            str(tdir),
            "--out",
            str(out),
            "--baseline",
            str(baseline),
        ]
    )
    assert rc == 0
    assert "no longer assertion-free" in capsys.readouterr().out

    # A new assertion-free test must fail the gate and be named.
    weak.write_text(
        "def test_weak():\n    assert True\n" "def test_new_weak():\n    pass\n"
    )
    rc = sa.main(
        [
            "--static-only",
            "--tests",
            str(tdir),
            "--out",
            str(out),
            "--baseline",
            str(baseline),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 1
    assert f"{weak}::test_new_weak" in captured.err


def test_baseline_gate_fails_closed_when_missing(tmp_path, capsys):
    tdir = tmp_path / "tests"
    tdir.mkdir()
    (tdir / "test_s.py").write_text("def test_ok():\n    assert 1\n")

    rc = sa.main(
        [
            "--static-only",
            "--tests",
            str(tdir),
            "--out",
            str(tmp_path / "out"),
            "--baseline",
            str(tmp_path / "missing.json"),
        ]
    )

    assert rc == 1
    assert "not found" in capsys.readouterr().err
