"""把 DEEPSEEK_API_KEY 环境变量里的值写进已安装扩展的偏好设置，并保存用户偏好。

密钥只从环境变量读，不写进这个文件。

用法：
  DEEPSEEK_API_KEY=sk-xxx blender.exe --background -P dev/configure_key.py
"""
import importlib
import os

import bpy

PKG = "bl_ext.user_default.blender_deepseek_agent"
DISK_NAME = "blender_deepseek_agent"

print("CFG factory_startup=", bpy.app.factory_startup)
ext_dir = bpy.utils.user_resource("EXTENSIONS")
for root, dirs, files in os.walk(ext_dir):
    if DISK_NAME in dirs:
        print("CFG on_disk=", root)

addon = bpy.context.preferences.addons.get(PKG)
if addon is None:
    try:
        bpy.ops.preferences.addon_enable(module=PKG)
    except Exception as error:
        print("CFG enable_failed", type(error).__name__, error)
    addon = bpy.context.preferences.addons.get(PKG)

print("CFG enabled=", addon is not None)
if addon is None:
    raise SystemExit(1)

key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
print("CFG key_in_env=", bool(key), "len=", len(key))
if not key:
    raise SystemExit(2)

prefs = addon.preferences
prefs.api_key = key
print("CFG stored_len=", len(prefs.api_key), "model=", prefs.model, "base_url=", prefs.base_url)
bpy.ops.wm.save_userpref()
print("CFG userpref_saved")

module = importlib.import_module(PKG)
cfg = module.config.get_config()
print("CFG readback source=", cfg["key_source"], "len=", len(cfg["api_key"]), "model=", cfg["model"])
