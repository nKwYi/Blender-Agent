# -*- coding: utf-8 -*-
"""把 #biz-export 导出的 ui.py 落成一个文本文件，供人直接看代码质量。"""
import html
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WB = os.path.join(ROOT, "ui_workbench")
OUT = os.path.join(ROOT, "docs", "shots", "exported_ui_py.txt")

BROWSERS = [
    os.environ.get("UW_BROWSER"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]


def main():
    exe = next((p for p in BROWSERS if p and os.path.exists(p)), None)
    if not exe:
        print("SKIP no browser")
        return 1
    url = pathlib.Path(os.path.join(WB, "index.html")).as_uri() + "#biz-export"
    prof = tempfile.mkdtemp(prefix="uw_py_")
    try:
        r = subprocess.run(
            [exe, "--headless=new", "--disable-gpu", "--no-first-run",
             "--no-default-browser-check", "--user-data-dir=" + prof,
             "--window-size=1400,1200", "--virtual-time-budget=9000",
             "--dump-dom", url], capture_output=True, timeout=180)
        dom = r.stdout.decode("utf-8", "replace")
    finally:
        shutil.rmtree(prof, ignore_errors=True)
    m = re.search(r'<div id="biz-export"[^>]*data-py-lines="(\d+)"[^>]*data-py="([^"]*)"', dom)
    if not m:
        print("EXPORT_DUMP_FAIL 抓不到 data-py")
        return 1
    src = html.unescape(m.group(2))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(src + "\n")
    raw = open(OUT, "rb").read()
    if b"\x00" in raw:
        print("EXPORT_NUL")
        return 1
    print("EXPORT_OK lines=%s declared=%s file=%s"
          % (len(src.split("\n")), m.group(1), OUT))
    return 0


sys.exit(main())
