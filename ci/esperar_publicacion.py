"""Waits until GitHub serves this commit to students: the raw installer and the zip.

GitHub caches both for some minutes after a push; the real-install check must test what was
just published, not the version before it.
"""

from __future__ import annotations

import io
import os
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

RAW = "https://raw.githubusercontent.com/PabloPC05/campus-usc/main/instalar.py"
ZIP = "https://github.com/PabloPC05/campus-usc/archive/refs/heads/main.zip"


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(f"{url}?t={time.time()}", timeout=60) as response:
        return response.read()


def main() -> int:
    local = Path(__file__).resolve().parents[1].joinpath("instalar.py").read_bytes()
    sha = os.environ.get("GITHUB_SHA", "")
    for attempt in range(60):
        raw_ok = fetch(RAW).replace(b"\r\n", b"\n") == local.replace(b"\r\n", b"\n")
        zip_ok = not sha or sha.encode() in zipfile.ZipFile(io.BytesIO(fetch(ZIP))).comment
        if raw_ok and zip_ok:
            print(f"GitHub ya sirve esta versión (intento {attempt + 1}).")
            return 0
        time.sleep(15)
    print("GitHub sigue sirviendo otra versión tras 15 minutos.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
