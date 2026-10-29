"""Autorreparación de `scripts/dev/admin_stack.sh` (plan 204).

Los tests usan un `astro` simulado y procesos falsos con una marca de dueño
única, así que nunca tocan un stack del admin real que esté corriendo.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import textwrap
import time
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "dev" / "admin_stack.sh"

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="usa /proc y setsid"
)

ASTRO_STUB = textwrap.dedent("""\
    #!/usr/bin/env bash
    # astro simulado: el "bloqueo" es un archivo con "pid puerto".
    lock="$STUB_LOCK"
    case "$1 $2" in
      "dev status")
        [[ -s "$lock" ]] || { echo '{"message":"No dev server running"}'; exit 1; }
        read -r pid port <"$lock"
        echo "{\\"message\\":\\"Dev server running at http://localhost:$port (pid $pid, uptime 1s)\\"}"
        ;;
      "dev stop")
        [[ -s "$lock" ]] && { read -r pid _ <"$lock"; kill "$pid" 2>/dev/null; : >"$lock"; }
        ;;
    esac
    """)

FAKE_SERVER = textwrap.dedent("""\
    import http.server, os
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
        def log_message(self, *a):
            pass
    port = int(os.environ["SERVING_PORT"])
    http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()
    """)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_port(port: int) -> None:
    for _ in range(50):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.1)
    raise AssertionError(f"el puerto {port} nunca abrió")


def _alive(proc: subprocess.Popen) -> bool:
    return proc.poll() is None


@pytest.fixture
def env(tmp_path: Path):
    pkg = tmp_path / "fake" / "news_collector" / "serving"
    pkg.mkdir(parents=True)
    (pkg.parent / "__init__.py").write_text("")
    (pkg / "__init__.py").write_text("")
    (pkg / "__main__.py").write_text(FAKE_SERVER)
    astro = tmp_path / "astro"
    astro.write_text(ASTRO_STUB)
    astro.chmod(0o755)
    lock = tmp_path / "lock"
    lock.write_text("")
    owner = f"test-{uuid.uuid4()}"
    procs: list[subprocess.Popen] = []

    def spawn(port: int, extra: dict[str, str]) -> subprocess.Popen:
        proc = subprocess.Popen(
            [sys.executable, "-m", "news_collector.serving"],
            cwd=tmp_path / "fake",
            env={**os.environ, "SERVING_PORT": str(port), **extra},
            start_new_session=True,
        )
        procs.append(proc)
        _wait_port(port)
        return proc

    def run(mode: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(SCRIPT)],
            env={
                **os.environ,
                "ADMIN_STACK_MODE": mode,
                "ADMIN_ASTRO_BIN": str(astro),
                "ADMIN_STACK_OWNER_ID": owner,
                "ADMIN_STACK_STATE_DIR": str(tmp_path / "state"),
                "STUB_LOCK": str(lock),
            },
            capture_output=True,
            text=True,
            timeout=60,
        )

    def gui(api_target: str) -> subprocess.Popen:
        port = _free_port()
        proc = spawn(port, {"ADMIN_API_TARGET": api_target})
        lock.write_text(f"{proc.pid} {port}\n")
        return proc

    def events() -> str:
        log = tmp_path / "state" / "events.log"
        return log.read_text() if log.exists() else ""

    yield type(
        "Env",
        (),
        {
            "spawn": staticmethod(spawn),
            "run": staticmethod(run),
            "gui": staticmethod(gui),
            "events": staticmethod(events),
            "owner": owner,
        },
    )
    for proc in procs:
        if _alive(proc):
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()


def test_healthy_stack_is_reused(env) -> None:
    api_port = _free_port()
    env.spawn(api_port, {"ADMIN_STACK_OWNER": env.owner})
    gui = env.gui(f"http://localhost:{api_port}")

    result = env.run("reuse")

    assert result.returncode == 0, result.stderr
    assert "se reutiliza" in result.stdout
    assert _alive(gui)
    assert "reused" in env.events()


def test_gui_without_api_is_reported_then_healed(env) -> None:
    gui = env.gui(f"http://localhost:{_free_port()}")

    status = env.run("status")
    assert status.returncode == 1
    assert "stack roto" in status.stderr
    assert _alive(gui), "status no debe detener nada"

    heal = env.run("heal")
    assert heal.returncode == 0, heal.stderr
    gui.wait(timeout=10)
    assert "healed stale_gui" in env.events()


def test_orphan_api_is_healed_but_foreign_api_is_left_alone(env) -> None:
    orphan = env.spawn(_free_port(), {"ADMIN_STACK_OWNER": env.owner})
    foreign = env.spawn(_free_port(), {})  # p. ej. un `make serve` manual

    assert env.run("status").returncode == 1
    heal = env.run("heal")

    assert heal.returncode == 0, heal.stderr
    orphan.wait(timeout=15)
    assert _alive(foreign)
    assert "healed orphan_api" in env.events()


def test_nothing_running(env) -> None:
    result = env.run("status")

    assert result.returncode == 0
    assert "no hay ningún stack" in result.stdout


def test_invalid_mode_is_rejected(env) -> None:
    result = env.run("bogus")

    assert result.returncode == 1
    assert "debe ser reuse" in result.stderr
