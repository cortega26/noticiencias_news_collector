"""Pruebas de humo de las herramientas de test añadidas en el plan 196."""

from __future__ import annotations

import datetime as dt
import tomllib
from pathlib import Path

import httpx
import respx
import time_machine

ROOT = Path(__file__).resolve().parents[3]


@respx.mock
def test_respx_intercepta_httpx_sin_red() -> None:
    route = respx.get("https://example.invalid/feed").mock(
        return_value=httpx.Response(200, text="<rss/>")
    )

    response = httpx.get("https://example.invalid/feed")

    assert route.called
    assert response.text == "<rss/>"


@time_machine.travel(dt.datetime(2030, 1, 2, 3, 4, tzinfo=dt.UTC), tick=False)
def test_time_machine_congela_el_reloj() -> None:
    assert dt.datetime.now(dt.UTC) == dt.datetime(2030, 1, 2, 3, 4, tzinfo=dt.UTC)


def test_contrato_de_capas_cubre_los_modulos_de_politica() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    contracts = config["tool"]["importlinter"]["contracts"]
    sources = {module for c in contracts for module in c["source_modules"]}

    assert {
        "news_collector.scoring",
        "news_collector.taxonomy",
        "news_collector.editorial",
    } <= sources
