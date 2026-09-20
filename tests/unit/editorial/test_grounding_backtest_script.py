import importlib.util
import sqlite3
from pathlib import Path


def _load():
    path = Path(__file__).resolve().parents[3] / "scripts" / "grounding_backtest.py"
    spec = importlib.util.spec_from_file_location("grounding_backtest_script", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_backtest_matches_source_by_url_and_skips_mismatches(tmp_path, capsys):
    mod = _load()
    db = tmp_path / "n.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "create table articles (id integer, title text, summary text, content text, url text)"
    )
    body = "Recovery was 91 percent over 25 days. " * 60
    conn.execute(
        "insert into articles values (1,'T','S',?,?)", (body, "https://x.org/a?rss=1")
    )
    conn.execute(
        "insert into articles values (2,'T','S',?,?)", (body, "https://x.org/OTHER")
    )
    conn.commit()
    conn.close()
    posts = tmp_path / "posts"
    posts.mkdir()
    for name, rid in (("ok.md", 1), ("mismatch.md", 2), ("noid.md", None)):
        idline = f"refinery_id: '{rid}'\n" if rid else ""
        (posts / name).write_text(
            f"---\n{idline}source_url: https://www.x.org/a/\n---\nRecuperación de 77 %.\n",
            encoding="utf-8",
        )
    results = mod.run(posts, db)
    assert [r["post"] for r in results] == ["ok.md"]
    assert results[0]["report"].errors  # 77 is not in the source
    assert mod.main(["--posts", str(posts), "--db", str(db)]) == 0
    assert "1 posts with source text" in capsys.readouterr().out


def test_url_identity_keeps_query_ids_and_requires_a_post_url(tmp_path):
    import sqlite3

    mod = _load()
    db = tmp_path / "n.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "create table articles (id integer, title text, summary text, content text, url text)"
    )
    conn.execute(
        "insert into articles values (1,'T','S','body','https://e.org/a?id=1&utm_source=x')"
    )
    conn.commit()
    same = mod.source_text(conn, 1, "https://e.org/a?id=1")
    other_id = mod.source_text(conn, 1, "https://e.org/a?id=2")
    no_url = mod.source_text(conn, 1, "")
    conn.close()
    assert same and other_id == "" and no_url == ""
    assert mod._url_key("https://e.org/x/1?rss=1") == mod._url_key("http://e.org/x/1")
