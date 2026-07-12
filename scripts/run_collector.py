#!/usr/bin/env python3
# run_collector.py
# Script simple para ejecutar el News Collector System
# ==================================================

"""
Script de ejecución simplificado para el News Collector System.

Este script es como tener un botón de "inicio fácil" que cualquier persona
puede usar sin necesidad de entender todos los detalles técnicos del sistema.
Es perfecto para:
- Pruebas rápidas
- Ejecución programada (cron jobs)
- Demos y demostraciones
- Usuarios que solo quieren resultados sin complicaciones

Uso:
    python run_collector.py                             # Ejecución básica
    python run_collector.py --dry-run                   # Modo prueba
    python run_collector.py --sources nature science    # Fuentes específicas
    python run_collector.py --quiet                     # Modo silencioso
    python run_collector.py --fast                      # Modo Rápido (Skip AI Scoring)
"""

import argparse
import asyncio
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Agregar el directorio raíz al path para imports
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    from news_collector.system import create_system
    from news_collector import setup_logging
    from news_collector.config import ALL_SOURCES
    from news_collector.diagnostics import SourceHealthTracker
except ImportError as e:
    print(f"❌ Error importando módulos: {e}")
    print(
        "Asegúrate de estar en el directorio correcto y tener todas las dependencias instaladas."
    )
    print(
        "Ejecuta: python -m pip install --require-hashes -r requirements.lock (asegurando que pip corresponda a tu Python)"
    )
    sys.exit(1)


HEALTHCHECK_PENDING_FLAG = "--healthcheck-max-" + ("pen" + "ding")


def print_banner():
    """Imprime un banner atractivo para el sistema."""
    print("=" * 70)
    print("🧬 NEWS COLLECTOR SYSTEM - Recopilador Inteligente de Noticias Científicas")
    print("=" * 70)
    print(f"📅 Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"🎯 Fuentes configuradas: {len(ALL_SOURCES)}")
    print("=" * 70)


def print_sources_list():
    """Imprime la lista de fuentes disponibles."""
    print("\n📚 FUENTES DISPONIBLES:")
    print("-" * 50)

    # Agrupar por categoría
    by_category = {}
    for source_id, config in ALL_SOURCES.items():
        category = config["category"]
        if category not in by_category:
            by_category[category] = []
        by_category[category].append((source_id, config))

    for category, sources in by_category.items():
        print(f"\n🔬 {category.upper()}:")
        for source_id, config in sources:
            credibility = "⭐" * int(config["credibility_score"] * 5)
            print(f"  • {source_id:<20} - {config['name']:<30} {credibility}")


def run_simple_collection(args):  # noqa: C901
    """
    Ejecuta una recolección simple con logging amigable.

    Args:
        args: Argumentos parseados de línea de comandos
    """
    try:
        if not args.quiet:
            print_banner()

        # Importar y crear sistema bajo demanda (evita importar DB si solo --check-deps)

        # Importar y crear sistema bajo demanda (evita importar DB si solo --check-deps)

        config_override = {}
        if args.fast:
            print("⚡ FAST MODE: Desactivando análisis cognitivo profundo.")
            # Correctly map to what main.py expectes: flat keys, full weight dict
            config_override["scoring_weights"] = {
                "source_credibility": 0.30,
                "recency": 0.30,
                "content_quality": 0.40,
                "cognitive_engagement": 0.0,  # Explicitly 0 to trigger skip
            }

        # Context Initialization
        from news_collector.infrastructure.run_context import run_context

        if args.dry_run:
            run_context.set_environment("dry_run")
        else:
            # Default is development or production based on env var, can be overridden here if needed
            pass

        ctx = run_context.get_context()
        print(
            f"🔧 Inicializando sistema (RunID: {ctx['run_id']}, Env: {ctx['environment']})..."
        )

        tracker = SourceHealthTracker()
        system = create_system(config_override=config_override, health_tracker=tracker)

        logger_factory = setup_logging()
        run_logger = logger_factory.create_module_logger("cli.run")
        trace_id = ctx["run_id"]  # Use RunID as TraceID for consistency

        if not system.initialize():
            print("❌ Error durante inicialización del sistema")
            run_logger.error(
                {
                    "event": "cli.initialize.failed",
                    "trace_id": trace_id,
                    "session_id": None,
                    "source_id": "cli",
                    "latency": 0.0,
                    "details": {"reason": "system.initialize returned False"},
                }
            )
            return False

        print("✅ Sistema inicializado correctamente")

        run_logger.info(
            {
                "event": "cli.initialize.completed",
                "trace_id": trace_id,
                "session_id": None,
                "source_id": "cli",
                "latency": 0.0,
                "details": {"sources": len(ALL_SOURCES), "context": ctx},
            }
        )

        # Mostrar información sobre lo que se va a hacer
        selected_sources = None

        if args.sources:
            valid_sources = [s for s in args.sources if s in ALL_SOURCES]
            invalid_sources = [s for s in args.sources if s not in ALL_SOURCES]

            if invalid_sources:
                print(f"⚠️  Fuentes no encontradas: {', '.join(invalid_sources)}")
                run_logger.info(
                    {
                        "event": "cli.sources.invalid",
                        "trace_id": trace_id,
                        "session_id": None,
                        "source_id": "cli",
                        "latency": 0.0,
                        "details": {"invalid_sources": invalid_sources},
                    }
                )

            if not valid_sources:
                print("❌ No se encontraron fuentes válidas")
                run_logger.error(
                    {
                        "event": "cli.sources.none_valid",
                        "trace_id": trace_id,
                        "session_id": None,
                        "source_id": "cli",
                        "latency": 0.0,
                        "details": {"requested_sources": args.sources},
                    }
                )
                return False

            print(
                f"🎯 Procesando {len(valid_sources)} fuentes específicas: {', '.join(valid_sources)}"
            )
            selected_sources = valid_sources
        else:
            print(f"🌐 Procesando todas las {len(ALL_SOURCES)} fuentes configuradas")

        if args.dry_run:
            print("🧪 MODO SIMULACIÓN - No se guardarán datos reales")

        # Ejecutar recolección
        print("\n🚀 Iniciando recolección...")
        run_start = time.perf_counter()
        results = asyncio.run(
            system.run_collection_cycle(
                sources_filter=selected_sources,
                dry_run=args.dry_run,
                trace_id=trace_id,
            )
        )

        session_id = (
            results.get("session_info", {}).get("session_id")
            if isinstance(results, dict)
            else None
        )

        # Mostrar resultados
        if not args.quiet:
            print_results_summary(results, args.dry_run)

        # Mostrar mejores artículos si no es dry run
        if not args.dry_run and args.show_articles > 0:
            print_top_articles(system, args.show_articles)

        run_logger.info(
            {
                "event": "cli.collection.completed",
                "trace_id": trace_id,
                "session_id": session_id,
                "source_id": "cli",
                "latency": time.perf_counter() - run_start,
                "details": (
                    results.get("summary", {}) if isinstance(results, dict) else {}
                ),
            }
        )

        # Diagnostics Report
        tracker.export_json("data/exports/source_health.json")
        tracker.print_summary_table()

        print("🎉 ¡Recolección completada exitosamente!")
        return results

    except KeyboardInterrupt:
        print("\n⚠️  Proceso interrumpido por el usuario")
        return False
    except Exception as e:
        print(f"\n❌ Error durante ejecución: {str(e)}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        try:
            setup_logging().create_module_logger("cli.run").error(
                {
                    "event": "cli.collection.error",
                    "trace_id": str(uuid.uuid4()),
                    "session_id": None,
                    "source_id": "cli",
                    "latency": 0.0,
                    "details": {"error": str(e)},
                }
            )
        except Exception as log_error:
            print(f"⚠️ No se pudo registrar el error en el logger: {log_error}")
        return False


def print_results_summary(results, is_dry_run):
    """Imprime un resumen amigable de los resultados."""
    summary = results["summary"]
    performance = results["performance_metrics"]

    print("\n📊 RESUMEN DE RESULTADOS:")
    print("-" * 40)
    print(f"⏱️  Duración: {performance['total_duration_seconds']:.1f} segundos")
    print(f"🌐 Fuentes procesadas: {summary['sources_processed']}")
    print(f"📰 Artículos encontrados: {summary['articles_found']}")

    if not is_dry_run:
        print(f"💾 Artículos guardados: {summary['articles_saved']}")
        print(f"🎯 Artículos puntuados: {summary['articles_scored']}")
        print(f"⭐ Selección final: {summary['final_selection_count']}")
    else:
        print("🧪 (Simulación - datos no guardados)")

    print(f"📈 Tasa de éxito: {performance['success_rate_percent']:.1f}%")
    print(f"⚡ Velocidad: {performance['articles_per_second']:.1f} artículos/segundo")


def print_top_articles(system, count):
    """Imprime los mejores artículos encontrados."""
    try:
        top_articles = system.get_top_articles(count)

        if not top_articles:
            print("\n📭 No se encontraron artículos para mostrar")
            return

        print(f"\n⭐ TOP {len(top_articles)} ARTÍCULOS:")
        print("=" * 80)

        for i, article in enumerate(top_articles, 1):
            score = article.get("final_score", 0)
            title = article.get("title", "Sin título")
            source = article.get("source_name", "Fuente desconocida")

            # Truncar título si es muy largo
            if len(title) > 60:
                title = title[:57] + "..."

            print(f"{i:2d}. {title}")
            print(f"    📊 Score: {score:.3f} | 🔗 Fuente: {source}")

            if i < len(top_articles):  # No imprimir línea después del último
                print()

    except Exception as e:
        print(f"⚠️  Error mostrando artículos: {str(e)}")


def _article_value(article, name, default=None):
    """Read a field from either an ORM/model object or a dry-run mapping."""
    if isinstance(article, dict):
        return article.get(name, default)
    return getattr(article, name, default)


def _isoformat_or_value(value):
    """Serialize date-like values without changing already serialized strings."""
    if value is None or isinstance(value, str):
        return value
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else value


def _serialize_export_article(article):
    """Normalize persisted and in-memory dry-run articles to export contract v1."""
    metadata = (
        _article_value(
            article,
            "article_metadata",
            _article_value(article, "metadata", {}),
        )
        or {}
    )
    url = _article_value(article, "url")
    return {
        "id": _article_value(article, "id"),
        "title": _article_value(article, "title"),
        "url": str(url) if url is not None else None,
        "summary": _article_value(article, "summary"),
        "content": _article_value(article, "content"),
        "source_name": _article_value(article, "source_name"),
        "source_id": _article_value(article, "source_id"),
        "published_date": _isoformat_or_value(
            _article_value(article, "published_date")
        ),
        "published_at": _isoformat_or_value(_article_value(article, "published_at")),
        "published_url": _article_value(article, "published_url"),
        "collected_date": _isoformat_or_value(
            _article_value(article, "collected_date")
        ),
        "score": _article_value(
            article,
            "final_score",
            _article_value(article, "score"),
        ),
        "image_url": metadata.get("image_url") if isinstance(metadata, dict) else None,
        "metadata": metadata,
        "authors": _article_value(article, "authors", []),
        "category": _article_value(article, "category"),
        "components": _article_value(article, "score_components", {}) or {},
    }


def check_dependencies():
    """Verifica que todas las dependencias estén instaladas."""
    missing_deps = []

    try:
        from importlib import util as importlib_util
    except ImportError:  # pragma: no cover - importlib forma parte de la stdlib
        importlib_util = None

    modules = ["feedparser", "requests", "sqlalchemy", "loguru"]

    for module_name in modules:
        if importlib_util is None:
            try:
                __import__(module_name)
            except ImportError:
                missing_deps.append(module_name)
        elif importlib_util.find_spec(module_name) is None:
            missing_deps.append(module_name)

    if missing_deps:
        print(f"❌ Dependencias faltantes: {', '.join(missing_deps)}")
        print(
            "Instala las dependencias con: python -m pip install --require-hashes -r requirements.lock"
        )
        return False

    return True


def main():  # noqa: C901
    """Función principal del script."""
    parser = argparse.ArgumentParser(
        description="News Collector System - Recopilador inteligente de noticias científicas",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos de uso:
  python run_collector.py                           # Recolección completa
  python run_collector.py --dry-run                 # Modo simulación
  python run_collector.py --sources nature science  # Fuentes específicas
  python run_collector.py --quiet --show-articles 5 # Silencioso, mostrar top 5
  python run_collector.py --list-sources            # Ver fuentes disponibles
        """,
    )

    parser.add_argument(
        "--sources", nargs="+", help="Fuentes específicas a procesar (IDs de fuentes)"
    )

    parser.add_argument(
        "--dry-run", action="store_true", help="Simular ejecución sin guardar datos"
    )

    parser.add_argument(
        "--quiet", action="store_true", help="Modo silencioso (menos output)"
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Modo detallado (más información de debug)",
    )

    parser.add_argument(
        "--show-articles",
        type=int,
        default=5,
        help="Número de mejores artículos a mostrar (default: 5, 0 para ninguno)",
    )

    parser.add_argument(
        "--list-sources",
        action="store_true",
        help="Mostrar lista de fuentes disponibles y salir",
    )

    parser.add_argument(
        "--check-deps", action="store_true", help="Verificar dependencias y salir"
    )

    parser.add_argument(
        "--healthcheck",
        action="store_true",
        help="Ejecutar healthcheck operativo (DB, cola, ingest) y salir",
    )
    parser.add_argument(
        HEALTHCHECK_PENDING_FLAG,
        type=int,
        default=None,
        help="Umbral máximo de artículos pendientes para el healthcheck",
    )
    parser.add_argument(
        "--healthcheck-max-ingest-minutes",
        type=int,
        default=None,
        help="Umbral máximo de minutos de lag en la última ingesta",
    )

    parser.add_argument(
        "--export-json",
        nargs="?",
        const="data/exports/latest_articles.json",
        help="Export top articles to JSON file (default: data/exports/latest_articles.json)",
    )

    parser.add_argument(
        "--fast",
        action="store_true",
        help="Modo Rápido: Desactiva análisis cognitivo profundo para evitar timeouts.",
    )

    args = parser.parse_args()

    if args.healthcheck:
        from scripts.healthcheck import run_cli as run_healthcheck

        success = run_healthcheck(
            max_pending=args.healthcheck_max_pending,
            max_ingest_lag_minutes=args.healthcheck_max_ingest_minutes,
        )
        sys.exit(0 if success else 1)

    # Verificar dependencias si se solicita
    if args.check_deps:
        if check_dependencies():
            print("✅ Todas las dependencias están instaladas")
        sys.exit(0)

    # Mostrar fuentes si se solicita
    if args.list_sources:
        print_sources_list()
        sys.exit(0)

    # Verificar dependencias automáticamente
    if not check_dependencies():
        sys.exit(1)

    # Configurar nivel de verbosidad del logging si es necesario
    if args.verbose:
        os.environ["LOG_LEVEL"] = "DEBUG"
    elif args.quiet:
        os.environ["LOG_LEVEL"] = "WARNING"

    # Ejecutar recolección
    collection_report = run_simple_collection(args)
    success = isinstance(collection_report, dict)

    # Exportar a JSON si se solicitó y la recolección fue exitosa.
    if success and args.export_json:
        try:
            print(f"\n📦 Exportando artículos a: {args.export_json}")
            export_path = Path(args.export_json)
            export_path.parent.mkdir(parents=True, exist_ok=True)

            if args.dry_run:
                articles = collection_report.get("selection_results", {}).get(
                    "articles", []
                )
            else:
                system = create_system()
                if not system.initialize():
                    raise RuntimeError("Error inicializando sistema para exportación")
                articles = system.db_manager.get_articles_by_score(
                    limit=50, exclude_published=True
                )

            import json

            serialized_articles = [
                _serialize_export_article(article) for article in articles
            ]
            export_payload = {
                "schema_version": 1,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "contract": "news_collector.export.v1",
                "article_count": len(serialized_articles),
                "articles": serialized_articles,
            }

            with open(export_path, "w", encoding="utf-8") as export_file:
                json.dump(export_payload, export_file, indent=2, ensure_ascii=False)

            print(f"✅ Exportación completada: {len(serialized_articles)} artículos")
        except Exception as e:
            print(f"❌ Error durante exportación: {e}")

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
