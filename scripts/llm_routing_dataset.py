"""Dataset selection for the LLM routing benchmark (spec-llm-routing-benchmark).

Matches the 40 published frontend posts to DB source rows by refinery_id,
stratifies by editorial category, tags hard items (preprint or unreviewed),
and backfills from completed rows when a post cannot be matched. Seeded and
reproducible; writes a case manifest plus selection provenance.

Usage:
    PYTHONPATH=. .venv/bin/python scripts/llm_routing_dataset.py \
        --out reports/evaluation/routing_benchmark_cases.jsonl [--seed 20260921]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = Path(
    os.environ.get("NOTICIENCIAS_FRONTEND_DIR", REPO_ROOT.parent / "noticiencias")
)
FRONTEND_POSTS = FRONTEND_DIR / "src" / "content" / "posts"
DB_PATH = REPO_ROOT / "data" / "news_v3.db"
PROMPTS_PATH = REPO_ROOT / "config" / "prompts.yaml"
MIN_CONTENT_CHARS = 750  # mirrors EditorAgent.min_content_length fallback
TARGET_N = 40

STRATA = ("ciencia", "salud", "tecnologia", "astrofisica")


def _slugify_category(name: str) -> str:
    slug = name.strip().lower()
    if slug in {"salud", "medicine", "health"}:
        return "salud"
    if slug in {
        "tecnología",
        "tecnologia",
        "technology",
        "artificial_intelligence",
        "ai",
        "computing",
    }:
        return "tecnologia"
    if slug in {"astronomía", "astronomia", "física", "fisica", "space", "physics"}:
        return "astrofisica"
    return "ciencia"


def _norm_url(url: str) -> str:
    return (url or "").strip().rstrip("/").lower()


def _parse_frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise ValueError(f"no frontmatter in {path}")
    data: dict = {}
    for key in ("title", "source_url", "refinery_id", "date"):
        m = re.search(rf"^{key}:\s*(.+)$", match.group(1), re.MULTILINE)
        if m:
            data[key] = m.group(1).strip().strip("'\"")
    if data.get("date"):
        data["date"] = data["date"][:10]
    cats = re.search(
        r"^categories:\s*\n((?:\s+-\s+.+\n)+)", match.group(1), re.MULTILINE
    )
    data["categories"] = (
        [c.strip() for c in re.findall(r"-\s+(.+)", cats.group(1))] if cats else []
    )
    return data


def _is_hard(row: dict, stratum: str) -> bool:
    """Hard stratum: preprints, or consequential health claims.

    `peer_reviewed` is NULL across the corpus, so it cannot discriminate.
    Health items about cancer/vaccines/trials are consequential by nature
    (wrong framing has real-world cost) — deterministic keyword rule,
    documented here so the choice is auditable, not cherry-picked.
    """
    if row.get("is_preprint"):
        return True
    if stratum == "salud":
        title = (row.get("title") or "").lower()
        if any(k in title for k in ("canc", "vac", "clinic", "trial", "ensayo")):
            return True
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed", type=int, default=20260921)
    args = parser.parse_args(argv)
    rng = random.Random(args.seed)

    posts = []
    for path in sorted(FRONTEND_POSTS.glob("*.md")):
        try:
            fm = _parse_frontmatter(path)
        except ValueError:
            continue
        if not fm.get("refinery_id"):
            continue
        posts.append({"file": path.name, **fm})

    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    by_id: dict[str, dict] = {}
    by_url: dict[str, dict] = {}
    for row in con.execute(
        "SELECT id, title, summary, content, content_mode, url, source_id,"
        " source_name, is_preprint, peer_reviewed, journal, doi, category,"
        " published_date, processing_status, language, LENGTH(content) AS nchars"
        " FROM articles"
    ):
        d = dict(row)
        by_id[str(d["id"])] = d
        if d["url"]:
            by_url.setdefault(_norm_url(d["url"]), d)
    con.close()

    def _row_for_post(post: dict) -> dict | None:
        # Primary key: source_url (stable across eras; old posts carry
        # title-ish refinery_id strings, new ones numeric DB ids).
        if post.get("source_url"):
            hit = by_url.get(_norm_url(post["source_url"]))
            if hit:
                return hit
        ref = str(post.get("refinery_id") or "")
        if ref.isdigit() and ref in by_id:
            return by_id[ref]
        return None

    matched, unmatched_files = [], []
    for post in posts:
        row = _row_for_post(post)
        if row is None or (row["nchars"] or 0) < MIN_CONTENT_CHARS:
            unmatched_files.append(post["file"])
            continue
        cats = post.get("categories") or ["Ciencia"]
        stratum = _slugify_category(cats[0])
        # Canonical date for replay: the shipped post date when matched
        # (production frontmatter fidelity), else the DB publication date.
        # process_article requires it explicitly (LAW-B5: no runtime clock).
        canonical_date = post.get("date") or str(row["published_date"] or "")[:10]
        matched.append(
            {
                "db_id": str(row["id"]),
                "stratum": stratum,
                "hard": _is_hard(row, stratum),
                "canonical_date": canonical_date,
                "source_title": row["title"],
                "source_url": row["url"],
                "post_file": post["file"],
                "post_title": post.get("title", ""),
                "nchars": row["nchars"],
                "origin": "published-match",
            }
        )

    # Quota fill from completed DB rows (deterministic): hard items first
    # (preprints, then consequential-health keywords), then stratum balance.
    # Targets keep every stratum analyzable; overflow lands in ciencia.
    have = {m["db_id"] for m in matched}
    STRATUM_TARGETS = {"ciencia": 14, "tecnologia": 12, "salud": 8, "astrofisica": 6}
    HARD_TARGET = 10
    if len(matched) < TARGET_N:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        pool = [
            dict(r)
            for r in con.execute(
                "SELECT id, title, url, is_preprint, peer_reviewed, category,"
                " published_date, LENGTH(content) AS nchars FROM articles"
                " WHERE processing_status IN ('completed','publishing')"
                " AND language = 'en' AND LENGTH(content) >= ?",
                (MIN_CONTENT_CHARS,),
            )
        ]
        con.close()
        rng.shuffle(pool)

        def stratum_of(row: dict) -> str:
            return _slugify_category((row["category"] or "ciencia").split(",")[0])

        def take(row: dict, selection: str) -> None:
            stratum = stratum_of(row)
            matched.append(
                {
                    "db_id": str(row["id"]),
                    "stratum": stratum,
                    "hard": _is_hard(row, stratum),
                    "canonical_date": str(row.get("published_date") or "")[:10],
                    "source_title": row["title"],
                    "source_url": row["url"],
                    "post_file": None,
                    "post_title": None,
                    "nchars": row["nchars"],
                    "origin": "completed-backfill",
                    "selection": selection,
                }
            )
            have.add(str(row["id"]))

        for m in matched:
            m["selection"] = "published-match"

        counts = {s: sum(1 for m in matched if m["stratum"] == s) for s in STRATA}
        hard_have = sum(1 for m in matched if m["hard"])

        # Pass 1: hard quota — preprints first, then salud-keyword items.
        for row in list(pool):
            if len(matched) >= TARGET_N or hard_have >= HARD_TARGET:
                break
            s = stratum_of(row)
            if row.get("is_preprint") or (
                s == "salud"
                and any(
                    k in (row["title"] or "").lower()
                    for k in ("canc", "vac", "clinic", "trial", "ensayo")
                )
            ):
                take(row, "quota-hard")
                pool.remove(row)
                counts[s] += 1
                hard_have += 1

        # Pass 2: stratum quotas, scarcest first.
        for row in list(pool):
            if len(matched) >= TARGET_N:
                break
            s = stratum_of(row)
            scarcest = sorted(STRATA, key=lambda x: counts[x] - STRATUM_TARGETS[x])
            if s == scarcest[0] or counts[s] < STRATUM_TARGETS[s]:
                take(row, f"quota-stratum-{s}")
                pool.remove(row)
                counts[s] += 1
                hard_have += sum(1 for m in matched[-1:] if m["hard"])

        # Pass 3: any remaining slots, pool order (seeded).
        for row in list(pool):
            if len(matched) >= TARGET_N:
                break
            take(row, "quota-overflow")
            pool.remove(row)

    # Order deterministically: stratum, hard-first, db_id.
    matched.sort(key=lambda m: (m["stratum"], not m["hard"], m["db_id"]))
    cases = matched[:TARGET_N]

    prompts_hash = hashlib.sha256(PROMPTS_PATH.read_bytes()).hexdigest()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for case in cases:
            fh.write(json.dumps(case, ensure_ascii=False) + "\n")

    hard_n = sum(1 for c in cases if c["hard"])
    strata = {s: sum(1 for c in cases if c["stratum"] == s) for s in STRATA}
    print(
        json.dumps(
            {
                "cases": len(cases),
                "matched_published": sum(
                    1 for c in cases if c["origin"] == "published-match"
                ),
                "backfilled": sum(
                    1 for c in cases if c["origin"] == "completed-backfill"
                ),
                "hard": hard_n,
                "strata": strata,
                "unmatched_files": unmatched_files,
                "seed": args.seed,
                "prompts_sha256": prompts_hash,
                "out": str(out),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
