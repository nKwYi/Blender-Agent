# -*- coding: utf-8 -*-
"""三张验收截图（无头 Edge，不开 GUI、不启 Blender）。

  1. shot1_shelf.png   打开就是业务块控件架（第一眼看得见有哪几块）
  2. shot2_canvas.png  插了 6 块之后的预览 + 积木列表
  3. shot3_export.png  导出面板（要看代码质量）

路径里的空格用字面空格写，URL 里用 %20——反过来就开不出来。
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WB = os.path.join(ROOT, "ui_workbench")
OUT = os.path.join(ROOT, "docs", "shots")

BROWSERS = [
    os.environ.get("UW_BROWSER"),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]


def find_browser():
    for p in BROWSERS:
        if p and os.path.exists(p):
            return p
    return None


def main():
    exe = find_browser()
    if not exe:
        print("SHOT_SKIP 找不到 Edge/Chrome")
        return 1
    os.makedirs(OUT, exist_ok=True)
    base = pathlib.Path(os.path.join(WB, "index.html")).as_uri()
    # 用 .as_uri() 生成的是 %20 编码过的 URL（正确）；下面的 out 只是文件路径，
    # 保留字面空格（Windows 自己认）。
    shots = [
        ("shot1_shelf.png", base + "#biz-empty", 1500, 1150),
        ("shot2_canvas.png", base + "#biz-demo", 1500, 1500),
        ("shot3_export.png", base + "#biz-export", 1500, 1900),
    ]
    prof = tempfile.mkdtemp(prefix="uw_shot_")
    ok = 0
    try:
        for fn, url, w, h in shots:
            dest = os.path.join(OUT, fn)
            if os.path.exists(dest):
                os.remove(dest)
            r = subprocess.run(
                [exe, "--headless=new", "--disable-gpu", "--no-first-run",
                 "--no-default-browser-check", "--user-data-dir=" + prof,
                 "--window-size=%d,%d" % (w, h), "--virtual-time-budget=9000",
                 "--hide-scrollbars", "--screenshot=" + dest, url],
                capture_output=True, timeout=240)
            size = os.path.getsize(dest) if os.path.exists(dest) else 0
            if size > 8000:
                ok += 1
                print("SHOT_OK %s %d bytes" % (dest, size))
            else:
                print("SHOT_FAIL %s rc=%s %s" % (dest, r.returncode, r.stderr[-200:]))
    finally:
        shutil.rmtree(prof, ignore_errors=True)
    print("SHOTS_DONE ok=%d/%d dir=%s" % (ok, len(shots), OUT))
    return 0 if ok == len(shots) else 1


sys.exit(main())
