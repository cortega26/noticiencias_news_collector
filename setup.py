#!/usr/bin/env python3
# setup.py
# Script de instalación y verificación para News Collector System
# ==============================================================

"""
Script de instalación inteligente para News Collector System.

Este script es como tener un asistente personal que:
- Verifica que tu sistema esté listo
- Instala todas las dependencias necesarias
- Configura el entorno inicial
- Ejecuta tests básicos para validar el funcionamiento integral
- Te guía paso a paso en caso de problemas

Es la manera más fácil y segura de poner el sistema en funcionamiento.
"""

import sys
import subprocess
import platform
from pathlib import Path
import time
import importlib.util
from types import ModuleType


def _load_version_metadata() -> ModuleType:
    """Load the version metadata module without importing the full config package."""

    version_module_path = Path(__file__).parent / "config" / "version.py"
    spec = importlib.util.spec_from_file_location(
        "config._version_metadata", version_module_path
    )
    if spec is None or spec.loader is None:
        raise ImportError("No se pudo cargar config/version.py")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_version_metadata = _load_version_metadata()
MIN_PYTHON_VERSION = _version_metadata.MIN_PYTHON_VERSION
PYTHON_REQUIRES_SPECIFIER = _version_metadata.PYTHON_REQUIRES_SPECIFIER


class NewsCollectorSetup:
    """
    Instalador inteligente para News Collector System.

    Esta clase maneja el proceso completo de instalación de manera
    robusta y amigable para el usuario.
    """

    def __init__(self):
        self.project_root = Path(__file__).parent
        self.python_version = sys.version_info
        self.platform_info = platform.system()
        self.errors = []
        self.warnings = []
        self.start_time = time.time()

        print("🚀 INSTALADOR DE NEWS COLLECTOR SYSTEM")
        print("=" * 50)
        print(f"📍 Directorio: {self.project_root}")
        print(
            f"🐍 Python: {self.python_version.major}.{self.python_version.minor}.{self.python_version.micro}"
        )
        print(f"💻 Sistema: {self.platform_info}")
        print("=" * 50)

    def run_setup(self):
        """
        Ejecuta el proceso completo de instalación.

        Returns:
            bool: True si la instalación fue exitosa
        """
        try:
            print("\n🔍 FASE 1: Verificando prerrequisitos...")
            if not self._check_prerequisites():
                return False

            print("\n📦 FASE 2: Instalando dependencias...")
            if not self._install_dependencies():
                return False

            print("\n⚙️  FASE 3: Configurando entorno...")
            if not self._setup_environment():
                return False

            print("\n💾 FASE 4: Inicializando base de datos...")
            if not self._initialize_database():
                return False

            print("\n🧪 FASE 5: Ejecutando tests de verificación...")
            if not self._run_verification_tests():
                return False

            print("\n✅ FASE 6: Configuración final...")
            self._final_setup()

            self._print_success_message()
            return True

        except KeyboardInterrupt:
            print("\n⚠️  Instalación interrumpida por el usuario")
            return False
        except Exception as e:
            print(f"\n❌ Error inesperado durante instalación: {str(e)}")
            return False

    def _check_prerequisites(self):
        """Verifica que el sistema cumpla con los prerrequisitos."""
        success = True

        # Verificar versión de Python
        print("  • Verificando versión de Python...")
        if (self.python_version.major, self.python_version.minor) < MIN_PYTHON_VERSION:
            self.errors.append(
                "Python "
                f"{PYTHON_REQUIRES_SPECIFIER} requerido, encontrado "
                f"{self.python_version.major}.{self.python_version.minor}"
            )
            success = False
        else:
            print(
                "    ✅ Python "
                f"{self.python_version.major}.{self.python_version.minor} "
                f"cumple {PYTHON_REQUIRES_SPECIFIER}"
            )

        # Verificar pip
        print("  • Verificando pip...")
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "--version"],
                check=True,
                capture_output=True,
            )
            print("    ✅ pip disponible")
        except subprocess.CalledProcessError:
            self.errors.append("pip no disponible")
            success = False

        # Verificar git (opcional pero recomendado)
        print("  • Verificando git...")
        try:
            subprocess.run(["git", "--version"], check=True, capture_output=True)
            print("    ✅ git disponible")
        except (subprocess.CalledProcessError, FileNotFoundError):
            self.warnings.append("git no disponible (opcional)")
            print("    ⚠️  git no encontrado (opcional)")

        # Verificar espacio en disco
        print("  • Verificando espacio en disco...")
        if self._check_disk_space():
            print("    ✅ Espacio suficiente")
        else:
            self.warnings.append("Poco espacio en disco disponible")

        return success

    def _install_dependencies(self):
        """Instala todas las dependencias de Python."""
        requirements_spec = self.project_root / "requirements.txt"
        lock_file = self.project_root / "requirements.lock"

        if not requirements_spec.exists():
            self.errors.append(
                f"Archivo requirements.txt no encontrado en {requirements_spec}"
            )
            return False

        if not lock_file.exists():
            self.errors.append(
                "Archivo requirements.lock no encontrado. Ejecuta "
                "'python -m piptools compile --generate-hashes --output-file requirements.lock requirements.txt'"
            )
            return False

        print(f"  • Instalando desde {lock_file}...")

        try:
            # Actualizar pip primero
            print("    • Actualizando pip...")
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "pip"],
                check=True,
                capture_output=True,
            )

            # Instalar dependencias
            print("    • Instalando dependencias principales...")
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--require-hashes",
                    "-r",
                    str(lock_file),
                ],
                capture_output=True,
                text=True,
            )

            if result.returncode != 0:
                print("    ❌ Error instalando dependencias:")
                print(f"    {result.stderr}")
                self.errors.append("Error en instalación de dependencias")
                return False

            print("    ✅ Dependencias instaladas correctamente")

            # Verificar instalación
            print("    • Verificando instalación...")
            if self._verify_package_installation():
                print("    ✅ Todas las dependencias verificadas")
                return True
            else:
                return False

        except subprocess.CalledProcessError as e:
            self.errors.append(f"Error ejecutando pip: {str(e)}")
            return False

    def _setup_environment(self):
        """Configura el entorno inicial."""
        env_example = self.project_root / ".env.example"
        env_file = self.project_root / ".env"

        # Crear archivo .env si no existe
        if not env_file.exists():
            if env_example.exists():
                print("  • Creando archivo .env desde .env.example...")
                try:
                    with open(env_example, "r") as source:
                        content = source.read()

                    with open(env_file, "w") as target:
                        target.write(content)

                    print("    ✅ Archivo .env creado")
                except Exception as e:
                    self.warnings.append(f"No se pudo crear .env: {str(e)}")
                    print(f"    ⚠️  Error creando .env: {str(e)}")
            else:
                self.warnings.append("Archivo .env.example no encontrado")
        else:
            print("  • Archivo .env ya existe, manteniéndolo")

        # Crear directorios necesarios
        print("  • Creando directorios necesarios...")
        directories = [self.project_root / "data", self.project_root / "data" / "logs"]

        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)
            print(f"    ✅ {directory.name}/ creado")

        return True

    def _initialize_database(self):
        """Inicializa la base de datos del sistema."""
        print("  • Configurando base de datos...")

        # Agregar el directorio del proyecto al path para imports
        sys.path.insert(0, str(self.project_root))

        try:
            # Importar y verificar módulos principales
            from config import validate_config, validate_sources
            from src.storage import get_database_manager

            print("    • Validando configuración...")
            validate_config()
            validate_sources()
            print("    ✅ Configuración válida")

            print("    • Inicializando base de datos...")
            db_manager = get_database_manager()

            # Verificar que las tablas se crearon
            health = db_manager.get_health_status()
            if health.get("status") != "healthy":
                self.warnings.append("Base de datos inicializada pero con advertencias")

            print("    ✅ Base de datos inicializada")
            return True

        except Exception as e:
            self.errors.append(f"Error inicializando base de datos: {str(e)}")
            print(f"    ❌ Error: {str(e)}")
            return False

    def _run_verification_tests(self):
        """Ejecuta tests de verificación para confirmar que el sistema funciona."""
        print("  • Ejecutando test de importación de módulos...")

        # Test 1: Importar módulos principales
        try:
            from config import ALL_SOURCES
            from src import RSSCollector, BasicScorer, get_database_manager

            print(
                f"    ✅ Módulos importados ({len(ALL_SOURCES)} fuentes configuradas)"
            )
        except Exception as e:
            self.errors.append(f"Error importando módulos: {str(e)}")
            return False

        # Test 2: Crear instancias básicas
        print("  • Probando creación de componentes...")
        try:
            collector = RSSCollector()
            scorer = BasicScorer()
            db_manager = get_database_manager()
            print("    ✅ Componentes creados correctamente")
        except Exception as e:
            self.errors.append(f"Error creando componentes: {str(e)}")
            return False

        # Test 3: Test de recolección simulada
        print("  • Ejecutando test de recolección simulada...")
        try:
            from main import create_system

            system = create_system()
            if system.initialize():
                # Ejecutar en modo dry-run con una sola fuente
                test_sources = {"nature": ALL_SOURCES["nature"]}
                results = system.collector.collect_from_multiple_sources(test_sources)

                if (
                    results.get("collection_summary", {}).get("sources_processed", 0)
                    > 0
                ):
                    print("    ✅ Test de recolección exitoso")
                else:
                    self.warnings.append("Test de recolección sin datos")
            else:
                self.errors.append("Error inicializando sistema para test")
                return False

        except Exception as e:
            self.warnings.append(f"Test de recolección falló: {str(e)}")
            print(f"    ⚠️  Test de recolección falló (no crítico): {str(e)}")

        return True

    def _final_setup(self):
        """Configuración final y limpieza."""
        print("  • Configuración final...")

        # Crear script de conveniencia si no existe
        run_script = self.project_root / "run.sh"
        if not run_script.exists() and self.platform_info != "Windows":
            try:
                with open(run_script, "w") as f:
                    f.write("#!/bin/bash\n")
                    f.write("# Script de conveniencia para ejecutar News Collector\n")
                    f.write('cd "$(dirname "$0")"\n')
                    f.write('python run_collector.py "$@"\n')

                run_script.chmod(0o755)
                print("    ✅ Script run.sh creado")
            except Exception as e:
                self.warnings.append(f"No se pudo crear run.sh: {str(e)}")

        # Mostrar resumen de configuración
        print("  • Configuración completada")

    def _check_disk_space(self):
        """Verifica que hay suficiente espacio en disco."""
        try:
            import shutil

            total, used, free = shutil.disk_usage(self.project_root)

            # Verificar que hay al menos 100MB libres
            min_free_mb = 100 * 1024 * 1024  # 100MB
            return free >= min_free_mb
        except OSError:
            return True  # Asumir OK si no podemos verificar

    def _verify_package_installation(self):
        """Verifica que los paquetes principales estén instalados correctamente."""
        # Map package names to their import names
        package_imports = {
            "feedparser": "feedparser",
            "requests": "requests",
            "sqlalchemy": "sqlalchemy",
            "loguru": "loguru",
            "beautifulsoup4": "bs4",
            "nltk": "nltk",
            "python-dateutil": "dateutil",
        }

        for package, import_name in package_imports.items():
            try:
                __import__(import_name)
            except ImportError:
                self.errors.append(f"Paquete {package} no instalado correctamente")
                return False

        return True

    def _print_success_message(self):
        """Imprime mensaje de éxito con instrucciones."""
        print("\n" + "🎉" * 50)
        print("¡INSTALACIÓN COMPLETADA EXITOSAMENTE!")
        print("🎉" * 50)

        if self.warnings:
            print(f"\n⚠️  Advertencias ({len(self.warnings)}):")
            for warning in self.warnings:
                print(f"  • {warning}")

        print("\n📋 PRÓXIMOS PASOS:")
        print("=" * 30)

        print("\n1️⃣  EJECUTAR PRIMERA RECOLECCIÓN (SIMULACIÓN):")
        print("   python run_collector.py --dry-run")

        print("\n2️⃣  VER FUENTES DISPONIBLES:")
        print("   python run_collector.py --list-sources")

        print("\n3️⃣  EJECUTAR RECOLECCIÓN REAL:")
        print("   python run_collector.py")

        print("\n4️⃣  VER MEJORES ARTÍCULOS:")
        print("   python run_collector.py --show-articles 10")

        print("\n5️⃣  PERSONALIZAR CONFIGURACIÓN:")
        print("   • Edita el archivo .env")
        print("   • Ajusta pesos de scoring según tus necesidades")
        print("   • Lee el README.md para configuración avanzada")

        print("\n📚 DOCUMENTACIÓN:")
        print("   • README.md - Guía completa")
        print("   • .env - Configuración del sistema")
        print("   • data/logs/ - Archivos de log")

        print("\n🆘 SOPORTE:")
        print("   • GitHub Issues para reportar problemas")
        print("   • README.md sección 'Troubleshooting'")

        print("\n✨ ¡Listo para recopilar las mejores noticias científicas del mundo!")


def main():
    """Función principal del instalador."""
    # Verificar que estamos en el directorio correcto
    expected_files = ["main.py", "requirements.txt", "requirements.lock", "config"]
    current_dir = Path.cwd()

    missing_files = [f for f in expected_files if not (current_dir / f).exists()]
    if missing_files:
        print("❌ Error: No pareces estar en el directorio del proyecto News Collector")
        print(f"Archivos/directorios faltantes: {', '.join(missing_files)}")
        print("\nAsegúrate de:")
        print("1. Estar en el directorio raíz del proyecto")
        print("2. Haber clonado el repositorio completo")
        sys.exit(1)

    # Crear y ejecutar instalador
    installer = NewsCollectorSetup()
    success = installer.run_setup()

    if success:
        print(
            f"\n🎯 Instalación completada en {time.time() - installer.start_time:.1f} segundos"
        )
        sys.exit(0)
    else:
        print("\n❌ INSTALACIÓN FALLÓ")
        print("=" * 30)

        if installer.errors:
            print(f"\n💥 Errores ({len(installer.errors)}):")
            for error in installer.errors:
                print(f"  • {error}")

        print("\n🆘 Para obtener ayuda:")
        print("  • Revisa el README.md")
        print(f"  • Verifica que tienes Python {PYTHON_REQUIRES_SPECIFIER}")
        print("  • Asegúrate de tener conexión a internet")
        print("  • Reporta el issue en GitHub con los errores mostrados")

        sys.exit(1)


if __name__ == "__main__":
    # Evitar que el script se ejecute desde otros directorios por error
    if Path(__file__).name != "setup.py":
        print("❌ Este script debe llamarse setup.py")
        sys.exit(1)

    main()

