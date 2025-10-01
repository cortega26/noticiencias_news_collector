import sys
import types
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

if "src" not in sys.modules:
    stub = types.ModuleType("src")
    stub.__path__ = [str(SRC_DIR)]
    sys.modules["src"] = stub

from config import ENRICHMENT_CONFIG
from src.contracts import CollectorArticleModel
from src.storage.database import DatabaseManager
from src.storage.models import Article

SIMHASH_MASK = (1 << 64) - 1


def _enrichment_model_version() -> str:
    default_model = ENRICHMENT_CONFIG.get("default_model", "pattern_v1")
    models = ENRICHMENT_CONFIG.get("models", {})
    model_config = models.get(default_model, {})
    return str(model_config.get("version", default_model))


def _article_payload(url: str, **overrides: object) -> dict[str, object]:
    base = {
        "url": url,
        "original_url": url,
        "title": "Artículo de prueba con simhash alto y contenido consistente",
        "summary": (
            "Resumen extenso utilizado para las pruebas de simhash y validación de contratos. "
            "Incluye suficiente longitud para cumplir los requisitos de contenido mínimo."
        ),
        "content": "Contenido adicional para el cálculo de simhash.",
        "source_id": "test_source",
        "source_name": "Test Source",
        "category": "science",
        "published_date": datetime.now(timezone.utc),
        "published_tz_offset_minutes": 0,
        "published_tz_name": "UTC",
        "authors": ["Autora de Prueba"],
        "language": "en",
        "word_count": 200,
        "reading_time_minutes": 2,
        "article_metadata": {
            "credibility_score": 0.75,
            "source_metadata": {"feed_title": "Test Feed"},
            "processing_timestamp": datetime.now(timezone.utc).isoformat(),
            "original_url": url,
            "enrichment": {
                "language": "en",
                "normalized_title": "articulo de prueba con simhash alto y contenido consistente",
                "normalized_summary": (
                    "resumen extenso utilizado para las pruebas de simhash y validacion de contratos. "
                    "incluye suficiente longitud para cumplir los requisitos de contenido minimo."
                ),
                "entities": ["Test Source"],
                "topics": ["science"],
                "sentiment": "neutral",
                "model_version": _enrichment_model_version(),
            },
        },
    }
    base.update(overrides)
    model = CollectorArticleModel.model_validate(base)
    return model.model_dump_for_storage()


def test_save_article_persists_signed_simhash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_path = tmp_path / "simhash.db"
    manager = DatabaseManager(database_config={"type": "sqlite", "path": db_path})

    high_value = (1 << 63) | 0x12345
    monkeypatch.setattr("src.storage.database.simhash64", lambda _: high_value)

    payload = _article_payload(
        "https://example.com/high-simhash", published_date=datetime(2024, 1, 2, 12, 30)
    )

    saved = manager.save_article(payload)
    assert saved is not None

    with manager.get_session() as session:
        stored = session.query(Article).filter_by(url=payload["url"]).one()
        assert stored.simhash == high_value - (1 << 64)
        assert (
            DatabaseManager._simhash_from_storage(stored.simhash)
            == high_value & SIMHASH_MASK
        )
        assert stored.simhash_prefix == ((high_value & SIMHASH_MASK) >> 48) & 0xFFFF
        assert stored.published_date is not None
        normalized = DatabaseManager._ensure_timezone(stored.published_date)
        assert normalized is not None
        assert normalized.tzinfo is not None
        assert normalized.utcoffset() == timedelta(0)


def test_time_distance_seconds_accepts_mixed_timezone_inputs() -> None:
    aware = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
    naive = datetime(2024, 1, 1, 0, 0)

    delta = DatabaseManager._time_distance_seconds(aware, naive)
    assert delta == 0.0
