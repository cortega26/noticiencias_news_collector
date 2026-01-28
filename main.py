# main.py
# Punto de entrada principal del News Collector System
# ==================================================

import argparse
import asyncio
import sys

from news_collector.system import create_system


def main():
    """
    Función principal para ejecución desde línea de comandos.
    """
    parser = argparse.ArgumentParser(description="News Collector System")
    parser.add_argument("--sources", nargs="+", help="Fuentes específicas a procesar")
    parser.add_argument(
        "--dry-run", action="store_true", help="Simular ejecución sin guardar datos"
    )
    parser.add_argument(
        "--top", type=int, default=10, help="Número de mejores artículos a mostrar"
    )
    parser.add_argument(
        "--stats", action="store_true", help="Mostrar estadísticas del sistema"
    )
    parser.add_argument(
        "--export-json", type=str, help="Ruta para exportar resultados a JSON"
    )
    parser.add_argument(
        "--max-items-per-source",
        type=int,
        help="Límite de artículos por fuente (override)",
    )

    args = parser.parse_args()

    try:
        # Override global config if requested (Runtime patching for dry-run/testing)
        if args.max_items_per_source:
            from news_collector.config.settings import COLLECTION_CONFIG

            print(
                f"🔧 Overriding max_articles_per_source to {args.max_items_per_source}"
            )
            COLLECTION_CONFIG["max_articles_per_source"] = args.max_items_per_source

        system = create_system()

        print("🔧 Inicializando sistema...")
        if not system.initialize():
            print("❌ Error durante inicialización")
            sys.exit(1)

        if args.stats:
            print("\n📊 ESTADÍSTICAS DEL SISTEMA:")
            stats = system.get_system_statistics()

            print(f"  • Sistema ID: {stats['system_info']['system_id']}")
            print(f"  • Uptime: {stats['system_info']['uptime_seconds']:.1f} segundos")
            print(
                f"  • Estado: {'Saludable' if stats['system_info']['is_healthy'] else 'Con problemas'}"
            )
            print(
                f"  • Artículos totales: {stats['database_health']['total_articles']}"
            )
            print(f"  • Fuentes activas: {stats['database_health']['active_sources']}")

        else:
            print("\n🚀 Ejecutando ciclo de recolección...")
            results = asyncio.run(
                system.run_collection_cycle(args.sources, args.dry_run)
            )

            if args.export_json:
                import json
                from pathlib import Path

                export_path = Path(args.export_json)
                export_path.parent.mkdir(parents=True, exist_ok=True)

                # En dry-run, usamos los resultados simulados
                # Para validación, aseguramos que la estructura coincida con lo esperado

                with open(export_path, "w", encoding="utf-8") as f:
                    json.dump(results, f, ensure_ascii=False, indent=2, default=str)
                print(f"\n💾 Resultados exportados a: {export_path}")

            print("\n📈 RESUMEN DE RESULTADOS:")
            summary = results["summary"]
            print(f"  • Fuentes procesadas: {summary['sources_processed']}")
            print(f"  • Artículos encontrados: {summary['articles_found']}")
            print(f"  • Artículos guardados: {summary['articles_saved']}")
            print(
                f"  • Artículos en selección final: {summary['final_selection_count']}"
            )

            if args.top > 0 and not args.dry_run:
                print(f"\n⭐ TOP {args.top} ARTÍCULOS:")
                top_articles = system.get_top_articles(args.top)

                for i, article in enumerate(top_articles, 1):
                    print(f"  {i}. {article['title'][:80]}...")
                    print(
                        f"     Score: {article['final_score']:.3f} | Fuente: {article['source_name']}"
                    )

        print("\n✅ Ejecución completada exitosamente!")

    except KeyboardInterrupt:
        print("\n⚠️  Ejecución interrumpida por usuario")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error durante ejecución: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
