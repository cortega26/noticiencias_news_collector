import importlib.util
import json
import sys
from pathlib import Path

_path = Path(__file__).resolve().parents[3] / "scripts" / "mutation_score.py"
_spec = importlib.util.spec_from_file_location("mutation_score_script", _path)
ms = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ms
_spec.loader.exec_module(ms)


def _write(root, name, codes):
    path = root / f"{name}.meta"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"exit_code_by_key": {f"m{i}": c for i, c in enumerate(codes)}})
    )


def test_scores_count_detected_survived_and_ignore_untested(tmp_path):
    _write(tmp_path, "pkg/a.py", [1, 1, 3, 36, 0, 0, 5, 33, 34, None])
    scores = ms.module_scores(tmp_path)
    assert scores["pkg/a.py"] == {"detected": 4, "survived": 2, "ignored": 4}
    assert round(ms.score(scores["pkg/a.py"]), 1) == 66.7


def test_unknown_exit_codes_count_against_the_score(tmp_path):
    _write(tmp_path, "b.py", [1, 99])
    scores = ms.module_scores(tmp_path)
    assert scores["b.py"] == {"detected": 1, "suspicious": 1}
    assert ms.score(scores["b.py"]) == 50.0


def test_score_is_none_without_judged_mutants():
    assert ms.score({"ignored": 3}) is None
    assert ms.score({}) is None


def test_check_flags_below_floor_and_missing_results():
    scores = {"a.py": {"detected": 8, "survived": 2}, "c.py": {"ignored": 1}}
    floors = {"a.py": 80.0, "b.py": 50.0, "c.py": 10.0}
    assert ms.check(scores, floors) == [
        "b.py: no mutation results (floor 50 %)",
        "c.py: no mutation results (floor 10 %)",
    ]
    assert ms.check({"a.py": {"detected": 7, "survived": 3}}, {"a.py": 80.0}) == [
        "a.py: 70.0 % < floor 80 %"
    ]


def test_render_and_main_check_exit_codes(tmp_path, capsys):
    mutants = tmp_path / "mutants"
    _write(mutants, "news_collector/x.py", [1, 1, 1, 0])
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.mutation.floors]\n"news_collector/x.py" = 70\n')
    assert (
        ms.main(["--mutants", str(mutants), "--pyproject", str(pyproject), "--check"])
        == 0
    )  # 75 % >= floor 70 %
    out = capsys.readouterr()
    assert (
        "| news_collector/x.py | 3 | 1 | 75.0 % |" in out.out and "**total**" in out.out
    )
    assert out.err == ""
    pyproject.write_text('[tool.mutation.floors]\n"news_collector/x.py" = 90\n')
    assert (
        ms.main(["--mutants", str(mutants), "--pyproject", str(pyproject), "--check"])
        == 1
    )
    assert "FAIL news_collector/x.py: 75.0 % < floor 90 %" in capsys.readouterr().err
    assert ms.main(["--mutants", str(mutants)]) == 0
