"""Dump the authoritative native-UILayout capability inventory for Blender 5.2.1.

This replaces the prose ceiling doc (blender_ui_ceiling.html, 2026-10-10) with a
machine-readable facts file. Headless only -- never opens a window.

Run:
    blender.exe --background --factory-startup -P dev/probe_native_api.py
"""
import json
import os
import sys

import bpy

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "ui_workbench", "native_api.json")

facts = {
    "blender_version": bpy.app.version_string,
    "python_version": sys.version.split()[0],
    "ui": {},
    "theme": {},
    "icons": {},
    "panels": {},
    "operators": {},
    "notes": [],
}


def _props(rna_type):
    """All settable/readable properties on an RNA type, minus internals."""
    out = {}
    for p in rna_type.bl_rna.properties:
        if p.identifier == "rna_type":
            continue
        item = {"type": p.type, "readonly": bool(p.is_readonly)}
        if p.type == "ENUM" and not p.is_readonly:
            try:
                item["items"] = [i.identifier for i in p.enum_items]
            except Exception as exc:  # pragma: no cover
                item["items_error"] = str(exc)
        out[p.identifier] = item
    return out


def _funcs(rna_type):
    """Every callable on the RNA type with its parameter names and defaults."""
    out = {}
    for f in rna_type.bl_rna.functions:
        if f.identifier in {"draw", "poll"}:
            continue
        params = []
        for prm in f.parameters:
            params.append({
                "name": prm.identifier,
                "type": prm.type,
                "required": bool(prm.is_required),
            })
        out[f.identifier] = params
    return out


# ---------------------------------------------------------------- UILayout
ui = bpy.types.UILayout
facts["ui"]["functions"] = _funcs(ui)
facts["ui"]["properties"] = _props(ui)

# Things the ceiling doc claims. Verify each one actually exists right now.
CLAIMS = {
    "label": ("functions",),
    "box": ("functions",),
    "row": ("functions",),
    "column": ("functions",),
    "split": ("functions",),
    "separator": ("functions",),
    "menu": ("functions",),
    "prop": ("functions",),
    "operator": ("functions",),
    "panel": ("functions",),
    "progress": ("functions",),
    "grid_flow": ("functions",),
    "template_ID": ("functions",),
    "context_pointer": ("functions",),
    "use_property_split": ("properties",),
    "use_property_decorate": ("properties",),
    "alert": ("properties",),
    "active": ("properties",),
    "enabled": ("properties",),
    "emboss": ("properties",),
    "scale_y": ("properties",),
    "alignment": ("properties",),
    "operator_context": ("properties",),
    "column_flow": ("functions",),
}
for name, (bucket,) in CLAIMS.items():
    present = name in facts["ui"][bucket]
    facts["notes"].append({
        "claim": "UILayout.%s" % name,
        "present": present,
        "bucket": bucket,
    })
    if not present:
        facts["notes"][-1]["verdict"] = "STALE -- ceiling doc listed this but it is absent"

# emboss enum values, spelled out so the registry can cite them
emb = facts["ui"]["properties"].get("emboss", {})
facts["ui"]["emboss_items"] = emb.get("items", [])

# No-FALSE-POSITIVE check: confirm the API surface has no arbitrary colour,
# no font size and no hover hook. These are the load-bearing negatives.
facts["ui"]["negatives"] = {
    "arbitrary_rgb": hasattr(ui, "color"),
    "font_size": "size" in facts["ui"]["functions"].get("label", []),
    "hover_hook": any("hover" in k.lower() for k in facts["ui"]["functions"]),
}

# ---------------------------------------------------------------- Theme
def _hex(val):
    """A theme Color slot -> #rrggbb.

    ThemeColor slots are bpy 'Color' values, NOT plain tuples. Read them with
    slice indexing; touching type(slot).bl_rna on a Color hard-exits Blender
    with no traceback. Background mode returns all-zero slots because the
    theme is not loaded -- callers must treat 000000 as 'not captured'.
    """
    try:
        seq = list(val)
    except TypeError:
        return None
    if len(seq) < 3:
        return None
    return "#%02x%02x%02x" % tuple(int(round(c * 255)) for c in seq[:3])


def _wcol(widget):
    """Pull the interesting slots out of one ThemeWidgetColors struct."""
    out = {}
    for slot in ("text", "text_sel", "inner", "inner_sel", "outline",
                 "outline_sel", "item"):
        sub = getattr(widget, slot, None)
        if sub is None:
            continue
        hexed = _hex(sub)
        if hexed and hexed != "#000000":
            out[slot] = hexed
    r = getattr(widget, "roundness", None)
    if isinstance(r, (int, float)):
        out["roundness"] = round(float(r), 4)
    return out


try:
    theme = bpy.context.preferences.themes[0]
    facts["theme"]["name"] = getattr(theme, "name", "?")
    # In Blender the wcol_* palette lives under theme.user_interface, NOT on
    # theme directly. Reading theme.wcol_* silently yields an empty dict.
    ui_theme = getattr(theme, "user_interface", None)
    facts["theme"]["user_interface_present"] = ui_theme is not None
    colors = {}
    if ui_theme is not None:
        for key in dir(ui_theme):
            if not key.startswith("wcol_"):
                continue
            slot = _wcol(getattr(ui_theme, key))
            if slot:
                colors[key] = slot
    facts["theme"]["colors"] = colors
    facts["theme"]["color_slot_count"] = len(colors)
    # A palette with only roundness means background mode: colours are zero.
    facts["theme"]["palette_captured"] = any(
        k for v in colors.values() for k in v if k != "roundness")
    if not facts["theme"]["palette_captured"]:
        facts["notes"].append({
            "claim": "theme palette readable in background mode",
            "present": False,
            "verdict": "STALE -- background mode zeroes the theme; "
                       "the palette MUST be captured from a GUI run",
        })
    # theme.panel_roundness / theme.region_outer_radius do NOT exist on the
    # Theme type -- roundness is per-widget inside ThemeWidgetColors.
    facts["theme"]["theme_level_roundness_readable"] = hasattr(theme, "panel_roundness")
except Exception as exc:
    facts["notes"].append({"claim": "theme read", "present": False, "error": str(exc)})

# ---------------------------------------------------------------- Icons
try:
    enums = ui.bl_rna.functions["operator"].parameters["icon"].enum_items
    facts["icons"]["count"] = len(enums)
    facts["icons"]["names"] = sorted(e.keys() for e in enums)
except Exception as exc:
    facts["notes"].append({"claim": "icon enum", "present": False, "error": str(exc)})

# ---------------------------------------------------------------- Panel
facts["panels"]["properties"] = _props(bpy.types.Panel)

# ---------------------------------------------------------------- The plugin
try:
    facts["operators"] = {
        "has_mouse_wheel_modifier": hasattr(bpy.types.Event, "mouse_wheel"),
        "has_mouse_region": hasattr(bpy.types.Event, "mouse_region"),
        "event_rna_fields": sorted(p.identifier for p in bpy.types.Event.bl_rna.properties),
    }
except Exception as exc:
    facts["notes"].append({"claim": "Event probe", "present": False, "error": str(exc)})

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(facts, fh, ensure_ascii=False, indent=2, sort_keys=True)

stale = [n for n in facts["notes"] if n.get("verdict")]
print("PROBE_OK wrote=%s" % OUT)
print("blender=%s functions=%d properties=%d icons=%d theme_widgets=%d"
      % (facts["blender_version"], len(facts["ui"]["functions"]),
         len(facts["ui"]["properties"]), facts["icons"].get("count", -1),
         facts["theme"].get("color_slot_count", -1)))
print("negatives=%s" % json.dumps(facts["ui"]["negatives"], sort_keys=True))
box = facts["theme"]["colors"].get("wcol_box", {})
print("wcol_box=%s" % json.dumps(box, sort_keys=True))
text = facts["theme"]["colors"].get("wcol_text", {})
print("wcol_text=%s" % json.dumps(text, sort_keys=True))
print("STALE_CLAIMS=%d" % len(stale))
for n in stale:
    print("  STALE: %s" % n["claim"])