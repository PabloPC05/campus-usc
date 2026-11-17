"""Checks, with every browser on this computer, that the sign-in window reaches the USC.

GitHub's machines (real Windows, Mac and Linux) run it with the Python of the installed
`campus`: each Chrome, Edge… is opened with no window and a temporary profile, with the same
arguments `campus entrar` uses, and must reach the USC's Microsoft sign-in page and be able to
read the Campus cookie. Nobody signs in: no account is used.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import websockets
from mcp_usc import system_browser as browsers

START = "https://cv.usc.es/auth/oidc/?source=loginpage"


def installed() -> list[tuple[str, str]]:
    """Every browser of the engine's list present here (not only the first, as campus does)."""

    found: list[tuple[str, str]] = []
    if sys.platform == "darwin":
        found = [(name, path) for name, path in browsers._MAC if Path(path).exists()]
    elif os.name == "nt":
        roots = [os.getenv(k) for k in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        for name, relative in browsers._WINDOWS:
            path = next(
                (Path(r) / relative for r in roots if r and (Path(r) / relative).exists()), None
            )
            if path:
                found.append((name, str(path)))
    else:
        for name, command in browsers._LINUX:
            path = shutil.which(command)
            if path and name not in {known for known, _ in found}:
                found.append((name, path))
    return found


async def check(name: str, executable: str) -> bool:
    profile = Path(tempfile.mkdtemp(prefix=f"campus-{name}-"))
    process = await asyncio.create_subprocess_exec(
        executable,
        f"--user-data-dir={profile}",
        "--remote-debugging-port=0",
        "--no-first-run",
        "--no-default-browser-check",
        "--password-store=basic",
        "--headless=new",
        "--disable-gpu",
        "about:blank",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    started = time.monotonic()
    try:
        port, path = await browsers._port_file(profile, process)
        async with websockets.connect(f"ws://127.0.0.1:{port}{path}", max_size=None) as socket:
            devtools = browsers._DevTools(socket)
            product = (await devtools.call("Browser.getVersion")).get("product")
            await devtools.open(START)
            url, pages = "", []
            for _ in range(45):
                await asyncio.sleep(1)
                targets = (await devtools.call("Target.getTargets")).get("targetInfos") or []
                pages = [t.get("url", "") for t in targets if t.get("type") == "page"]
                url = next((u for u in pages if "login.microsoftonline.com" in u), "")
                if url:
                    break
            cookies = (await devtools.call("Storage.getCookies")).get("cookies") or []
            campus = any(
                c.get("name") == "MoodleSession" and str(c.get("domain")).endswith("cv.usc.es")
                for c in cookies
            )
            ok = "login.microsoftonline.com" in url and campus
            mark = "✓" if ok else "✗"
            print(f"{mark} {name} ({product}): {time.monotonic() - started:.1f} s")
            where = url.split("?")[0] if url else f"ninguna página de Microsoft ({pages})"
            print(f"    llega a {where}; cookie del Campus: {campus}")
            await devtools.call("Browser.close")
            return ok
    except Exception as exc:  # noqa: BLE001 - reported, the run fails
        print(f"✗ {name}: {type(exc).__name__}: {exc}")
        return False
    finally:
        if process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), timeout=15)
            except TimeoutError:
                process.terminate()
        shutil.rmtree(profile, ignore_errors=True)


async def main() -> int:
    found = installed()
    print(f"Navegadores en este equipo: {', '.join(n for n, _ in found) or 'ninguno'}")
    print(f"campus usaría: {browsers.find_browser()}")
    if not found:
        return 1
    results = [await check(name, path) for name, path in found]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
