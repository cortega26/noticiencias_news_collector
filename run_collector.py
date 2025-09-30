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
"""

import sys
import os
from pathlib import Path
import argparse
from datetime import datetime

# Agregar el directorio raíz al path para imports
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

try:
    from config import ALL_SOURCES
except ImportError as e:
    print(f"❌ Error importando módulos: {e}")
    print(
        "Asegúrate de estar en el directorio correcto y tener todas las dependencias instaladas."
    )
    print(
        "Ejecuta: python -m pip install --require-hashes -r requirements.lock (asegurando que pip corresponda a tu Python)"
    )
    sys.exit(1)


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


def run_simple_collection(args):
    """
    Ejecuta una recolección simple con logging amigable.

    Args:
        args: Argumentos parseados de línea de comandos
    """
    try:
        if not args.quiet:
            print_banner()

        # Importar y crear sistema bajo demanda (evita importar DB si solo --check-deps)
        from main import create_system

        print("🔧 Inicializando sistema...")
        system = create_system()

        if not system.initialize():
            print("❌ Error durante inicialización del sistema")
            return False

        print("✅ Sistema inicializado correctamente")

        # Mostrar información sobre lo que se va a hacer
        if args.sources:
            valid_sources = [s for s in args.sources if s in ALL_SOURCES]
            invalid_sources = [s for s in args.sources if s not in ALL_SOURCES]

            if invalid_sources:
                print(f"⚠️  Fuentes no encontradas: {', '.join(invalid_sources)}")

            if not valid_sources:
                print("❌ No se encontraron fuentes válidas")
                return False

            print(
                f"🎯 Procesando {len(valid_sources)} fuentes específicas: {', '.join(valid_sources)}"
            )
        else:
            print(f"🌐 Procesando todas las {len(ALL_SOURCES)} fuentes configuradas")

        if args.dry_run:
            print("🧪 MODO SIMULACIÓN - No se guardarán datos reales")

        # Ejecutar recolección
        print("\n🚀 Iniciando recolección...")
        results = system.run_collection_cycle(
            sources_filter=args.sources if args.sources else None, dry_run=args.dry_run
        )

        # Mostrar resultados
        if not args.quiet:
            print_results_summary(results, args.dry_run)

        # Mostrar mejores artículos si no es dry run
        if not args.dry_run and args.show_articles > 0:
            print_top_articles(system, args.show_articles)

        print("🎉 ¡Recolección completada exitosamente!")
        return True

    except KeyboardInterrupt:
        print("\n⚠️  Proceso interrumpido por el usuario")
        return False
    except Exception as e:
        print(f"\n❌ Error durante ejecución: {str(e)}")
        if args.verbose:
            import traceback

            traceback.print_exc()
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


def check_dependencies():
    """Verifica que todas las dependencias estén instaladas."""
    missing_deps = []

    try:
        import feedparser
    except ImportError:
        missing_deps.append("feedparser")

    try:
        import requests
    except ImportError:
        missing_deps.append("requests")

    try:
        import sqlalchemy
    except ImportError:
        missing_deps.append("sqlalchemy")

    try:
        import loguru
    except ImportError:
        missing_deps.append("loguru")

    if missing_deps:
        print(f"❌ Dependencias faltantes: {', '.join(missing_deps)}")
        print(
            "Instala las dependencias con: python -m pip install --require-hashes -r requirements.lock"
        )
        return False

    return True


def main():
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

    args = parser.parse_args()

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
    success = run_simple_collection(args)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

# ¿Por qué este script de ejecución?
# =================================
#
# 1. SIMPLICIDAD: Interfaz muy fácil de usar para cualquier usuario,
#    sin necesidad de entender la complejidad interna.
#
# 2. FLEXIBILIDAD: Múltiples opciones para diferentes casos de uso:
#    testing, producción, debugging, etc.
#
# 3. ROBUSTEZ: Manejo de errores elegante y verificación de dependencias
#    automática.
#
# 4. INFORMATIVO: Output claro y útil que ayuda al usuario a entender
#    qué está pasando y qué resultados obtuvo.
#
# 5. DOCUMENTACIÓN INTEGRADA: Ejemplos de uso y help integrados
#    directamente en el script.
#
# 6. PREPARADO PARA AUTOMATIZACIÓN: Fácil de usar en scripts de cron
#    o sistemas de automatización.
#
# Este script es como tener un panel de control amigable para nuestro
# sistema sofisticado: toda la potencia del sistema, pero con una
# interfaz que hasta tu abuela podría usar.
