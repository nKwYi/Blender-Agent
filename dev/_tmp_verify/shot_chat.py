# -*- coding: utf-8 -*-
import os
import pathlib
import shutil
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
WB = os.path.join(ROOT, "ui_workbench")
OUT = os.path.join(ROOT, "docs", "shots")

BROWSERS = [
    os.environ.get("UW_BROWSER"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def find_browser():
    for p in BROWSERS:
        if p and os.path.exists(p):
            return p
    return None


def main():
    exe = find_browser()
    if not exe:
        print("SHOT_SKIP no browser")
        return 1
    os.makedirs(OUT, exist_ok=True)
    base = pathlib.Path(os.path.join(WB, "index.html")).as_uri()
    shots = [
        ("chat_qa_wide.png", base + "#biz-taball-chat", 1500, 1700),
        ("chat_qa_560.png", base + "#biz-taball-chat-wide", 1500, 1700),
    ]
    prof = tempfile.mkdtemp(prefix="uw_shot_")
    try:
        for fn, url, w, h in shots:
            dest = os.path.join(OUT, fn)
            if os.path.exists(dest):
                os.remove(dest)
            subprocess.run(
                [exe, "--headless=new", "--disable-gpu", "--no-first-run",
                 "--no-default-browser-check", "--user-data-dir=" + prof,
                 "--window-size=%d,%d" % (w, h), "--virtual-time-budget=9000",
                 "--hide-scrollbars", "--screenshot=" + dest, url],
                capture_output=True, timeout=240)
            print(fn, os.path.getsize(dest) if os.path.exists(dest) else 0)
    finally:
        shutil.rmtree(prof, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
