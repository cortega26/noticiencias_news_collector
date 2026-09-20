import importlib.util
import json
from pathlib import Path

from news_collector.quality import suite_audit as sa


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
    script = Path(__file__).resolve().parents[3] / "scripts" / "test_suite_audit.py"
    spec = importlib.util.spec_from_file_location("suite_audit_script", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
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
