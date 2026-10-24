"""Start the whole demo with one command: platform, control panel and bot.

    python run_demo.py           # normal run
    python run_demo.py --reset   # wipe history first for a clean demo
    python run_demo.py --show    # show the bot's browser while it works

Platform:       http://localhost:8000  (demo / demo1234)
Control panel:  http://localhost:8001
Stop everything with Ctrl+C.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser

PLATFORM_URL = "http://localhost:8000"
PANEL_URL = "http://localhost:8001"


def wait_for(url: str, timeout: float = 20) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except OSError:
            time.sleep(0.3)
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Arranca la demo completa")
    parser.add_argument("--reset", action="store_true", help="Borra el historial antes de empezar")
    parser.add_argument("--show", action="store_true", help="Muestra el navegador del bot mientras trabaja")
    parser.add_argument("--no-browser", action="store_true", help="No abre las webs automáticamente")
    args = parser.parse_args()

    py = sys.executable
    env = os.environ.copy()
    env["PORTAL_URL"] = PLATFORM_URL
    if args.show:
        env["HEADLESS"] = "false"

    seed = [py, "-m", "scripts.seed"] + (["--reset"] if args.reset else [])
    subprocess.run(seed, check=True, env=env)

    procs: list[subprocess.Popen[bytes]] = []
    try:
        procs.append(subprocess.Popen([py, "-m", "uvicorn", "portal.app:app", "--port", "8000",
                                       "--log-level", "warning"], env=env))
        procs.append(subprocess.Popen([py, "-m", "uvicorn", "dashboard.app:app", "--port", "8001",
                                       "--log-level", "warning"], env=env))
        if not (wait_for(f"{PLATFORM_URL}/health") and wait_for(PANEL_URL)):
            raise SystemExit("La plataforma o el panel no arrancaron. Revisa que los puertos 8000 y 8001 estén libres.")

        print(f"\n  Plataforma de asistencia: {PLATFORM_URL}  (demo / demo1234)")
        print(f"  Panel de control:         {PANEL_URL}")
        print("  Ctrl+C para pararlo todo\n")
        if not args.no_browser:
            webbrowser.open(PANEL_URL)
            webbrowser.open(PLATFORM_URL)

        bot = subprocess.Popen([py, "-m", "bot.main"], env=env)
        procs.append(bot)
        bot.wait()
    except KeyboardInterrupt:
        pass
    finally:
        for p in reversed(procs):
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=8)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    main()
