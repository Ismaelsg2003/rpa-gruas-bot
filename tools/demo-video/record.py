"""Record the demo video: panel + platform side by side with captions.

Usage (with the demo running: python run_demo.py --reset):
    cd tools/demo-video && python -m http.server 8002      # serves stage.html
    python tools/demo-video/record.py docs/video-raw       # in another terminal
Then convert with ffmpeg (see tools/demo-video/README.md).
"""
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch()
    # Log in to the platform first so its iframe shows the services list.
    ctx = browser.new_context(viewport={"width": 1920, "height": 1080},
                              record_video_dir=str(OUT), record_video_size={"width": 1920, "height": 1080})
    # The platform stops auto-refreshing for automated browsers; pretend we are a person.
    ctx.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => false})")
    login = ctx.new_page()
    login.goto("http://localhost:8000/login")
    login.fill("#username", "demo"); login.fill("#password", "demo1234")
    login.click("[data-testid=login-submit]")
    login.close()

    page = ctx.new_page()
    t0 = time.time()
    page.goto("http://localhost:8002/stage.html")
    page.wait_for_timeout(2500)
    panel = page.frame_locator("#panel")
    panel_frame = page.frame(url=lambda u: "8001" in u)

    def cap(n, text, hold):
        page.evaluate("([n, t]) => setCaption(n, t)", [n, text])
        page.wait_for_timeout(hold)

    cap(1, "La aseguradora publica servicios con cuenta atrás. Se los queda la primera empresa que los acepta.", 9000)
    cap(2, "El bot RPA los lee, aplica las reglas de la empresa y acepta en 2-4 s asignando la grúa adecuada.", 12000)
    cap(3, "El gerente lo ve todo en directo: qué acepta, qué descarta y por qué, y dónde está cada grúa.", 10000)

    cap(4, "Si retiro grúas, el bot sigue aceptando y pone los servicios en cola de la que antes quede libre.", 1500)
    for code in ("G-01", "A-04"):
        btn = panel.locator(".unit", has_text=code).locator(".unit-toggle")
        btn.click()
        page.wait_for_timeout(900)
    page.wait_for_timeout(11000)

    cap(5, "Las reglas se cambian desde el panel, sin tocar código: subo el importe mínimo a 90 €.", 1200)
    panel_frame.evaluate("document.getElementById('rules-sec').scrollIntoView({behavior: 'smooth'})")
    page.wait_for_timeout(1800)
    row = panel.locator(".rule", has_text="Importe mínimo")
    inp = row.locator("input[name=value]")
    inp.click(); inp.press("Control+a"); inp.type("90", delay=180)
    page.wait_for_timeout(500)
    row.locator("button[type=submit]").click()
    page.wait_for_timeout(2500)
    panel_frame.evaluate("document.getElementById('services-sec').scrollIntoView({behavior: 'smooth'})")
    page.wait_for_timeout(8000)
    panel_frame.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")

    cap(6, "Código, tests y despliegue: github.com/Ismaelsg2003/rpa-gruas-bot", 5000)
    print("duration", round(time.time() - t0, 1))
    video = page.video
    ctx.close()
    print("video", video.path())
    browser.close()
