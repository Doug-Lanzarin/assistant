"""Teste ponta a ponta do orb com ÁUDIO REAL (Chromium com microfone simulado por arquivo WAV).

Pré-requisitos: backend rodando em 127.0.0.1:8765 com voz instalada (faster-whisper + Piper),
playwright instalado e um WAV com uma frase falada (ex.: gerado pelo Piper).

  ORB_CHROME=/caminho/chrome ORB_FAKE_MIC=frase.wav python scripts/orb_e2e.py

Mede a correlação entre a amplitude do TTS e o raio do núcleo, a sequência de
estados e grava capturas + quadros (montáveis em vídeo com ffmpeg).
"""

import asyncio
import json
import os
import statistics

from playwright.async_api import async_playwright

OUT = os.environ.get("ORB_OUT", "data/orb-e2e")
BASE = os.environ.get("ORB_BASE", "http://127.0.0.1:8765")
CHROME = os.environ.get("ORB_CHROME", "/opt/pw-browsers/chromium")
FAKE_MIC = os.environ["ORB_FAKE_MIC"]


async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(
            executable_path=CHROME,
            args=[
                "--use-fake-ui-for-media-stream",
                "--use-fake-device-for-media-stream",
                "--use-file-for-fake-audio-capture=" + FAKE_MIC,
                "--autoplay-policy=no-user-gesture-required",
            ],
        )
        ctx = await b.new_context(viewport={"width": 1366, "height": 860})
        page = await ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))
        page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        import base64
        import os

        os.makedirs(f"{OUT}/frames", exist_ok=True)
        frames = []
        cdp = await ctx.new_cdp_session(page)

        async def on_frame(ev):
            frames.append((ev["metadata"]["timestamp"], ev["data"]))
            try:
                await cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
            except Exception:  # noqa: BLE001 - o screencast pode terminar antes do ack
                pass

        cdp.on("Page.screencastFrame", lambda ev: asyncio.ensure_future(on_frame(ev)))
        await page.goto(BASE)
        st = await page.evaluate("fetch('/api/auth/status').then(r=>r.json())")
        if st["has_user"]:
            await page.get_by_label("Usuário").fill("doug")
            await page.get_by_label("Senha", exact=True).fill("senha-forte-123")
            await page.get_by_role("button", name="Entrar").click()
        else:
            await page.get_by_label("Usuário").fill("doug")
            await page.get_by_label("Senha", exact=True).fill("senha-forte-123")
            await page.get_by_label("Confirmar senha").fill("senha-forte-123")
            await page.get_by_role("button", name="Criar acesso").click()
        os.makedirs(OUT, exist_ok=True)
        await page.get_by_text("Sessão de voz encerrada").wait_for()
        await page.wait_for_timeout(600)
        await page.screenshot(path=f"{OUT}/0-off.png")
        await cdp.send(
            "Page.startScreencast", {"format": "jpeg", "quality": 80, "maxWidth": 1366, "maxHeight": 860, "everyNthFrame": 1}
        )
        await page.get_by_role("button", name="Iniciar").click()
        boot = []
        for _ in range(12):
            boot.append(await page.evaluate("window.__jarvisOrb().params.presence"))
            await page.wait_for_timeout(100)
        await page.wait_for_timeout(1200)
        await page.screenshot(path=f"{OUT}/1-idle.png")
        idle = []
        for _ in range(30):
            idle.append(await page.evaluate("window.__jarvisOrb().coreRadius"))
            await page.wait_for_timeout(100)

        samples = []  # (t, state, level, radius, source)
        await page.get_by_role("button", name="Falar com o JARVIS").click()
        shots = set()
        t0 = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - t0 < 40:
            s = await page.evaluate("window.__jarvisOrb()")
            samples.append((round(asyncio.get_event_loop().time() - t0, 2), s["state"], s["level"], s["coreRadius"], s["source"]))
            if s["state"] not in shots and s["state"] in ("listening", "thinking", "speaking"):
                await page.wait_for_timeout(350 if s["state"] != "thinking" else 50)
                await page.screenshot(path=f"{OUT}/2-{s['state']}.png")
                shots.add(s["state"])
            if "speaking" in shots and s["state"] == "idle":
                break
            await page.wait_for_timeout(40)
        caption = await page.locator(".orb-caption").inner_text()
        await page.get_by_role("button", name="Encerrar").click()
        await page.wait_for_timeout(2500)
        await cdp.send("Page.stopScreencast")
        await page.screenshot(path=f"{OUT}/3-encerrado.png")
        frames[0][0]
        with open(f"{OUT}/frames/list.txt", "w") as lf:
            for i, (ts, data) in enumerate(frames):
                with open(f"{OUT}/frames/f{i:05d}.jpg", "wb") as ff:
                    ff.write(base64.b64decode(data))
                dur = (frames[i + 1][0] - ts) if i + 1 < len(frames) else 0.04
                lf.write(f"file 'f{i:05d}.jpg'\nduration {max(0.001, dur):.4f}\n")
        m = await ctx.new_page()
        await m.set_viewport_size({"width": 390, "height": 844})
        await m.goto(BASE + "/#/jarvis")
        await m.wait_for_timeout(800)
        await m.get_by_role("button", name="Iniciar sessão de voz").click()
        await m.wait_for_timeout(1500)
        await m.screenshot(path=f"{OUT}/4-mobile.png")
        await ctx.close()
        await b.close()

    def corr(xs, ys):
        mx, my = statistics.mean(xs), statistics.mean(ys)
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False))
        den = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
        return num / den if den else 0

    def by(st):
        return [s for s in samples if s[1] == st]
    sp, li = by("speaking"), by("listening")
    print(
        json.dumps(
            {
                "boot_presence": [round(x, 2) for x in boot],
                "idle_radius_min_max": [round(min(idle), 1), round(max(idle), 1)],
                "listening": {
                    "n": len(li),
                    "level_max": round(max((s[2] for s in li), default=0), 2),
                    "sources": sorted({s[4] for s in li}),
                },
                "thinking_n": len(by("thinking")),
                "speaking": {
                    "n": len(sp),
                    "sources": sorted({s[4] for s in sp}),
                    "level_min_max": [round(min((s[2] for s in sp), default=0), 2), round(max((s[2] for s in sp), default=0), 2)],
                    "radius_min_max": [
                        round(min((s[3] for s in sp), default=0), 1),
                        round(max((s[3] for s in sp), default=0), 1),
                    ],
                    "corr_level_radius": round(corr([s[2] for s in sp], [s[3] for s in sp]), 3) if len(sp) > 3 else None,
                },
                "state_sequence": [k for i, k in enumerate(s[1] for s in samples) if i == 0 or samples[i - 1][1] != k],
                "caption": caption,
                "errors": errs,
            },
            ensure_ascii=False,
            indent=1,
        )
    )


asyncio.run(main())
