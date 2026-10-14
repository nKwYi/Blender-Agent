import os

script_path = r"E:\Three JS\园区建设\AI大门装饰建模\Gemini版本\build_gate_gemini.py"
with open(script_path, "r", encoding="utf-8") as f:
    text = f.read()

replacements = [
    # 1. Silver material
    (
        'bsdf.inputs["Base Color"].default_value = (0.78, 0.80, 0.83, 1.0)\n    bsdf.inputs["Metallic"].default_value = 0.75\n    bsdf.inputs["Roughness"].default_value = 0.20',
        'bsdf.inputs["Base Color"].default_value = (0.58, 0.61, 0.64, 1.0)\n    bsdf.inputs["Metallic"].default_value = 0.85\n    bsdf.inputs["Roughness"].default_value = 0.24'
    ),
    # 2. Bronze pylon material
    (
        'bsdf.inputs["Base Color"].default_value = (0.33, 0.105, 0.075, 1.0)\n    bsdf.inputs["Metallic"].default_value = 0.68\n    bsdf.inputs["Roughness"].default_value = 0.22',
        'bsdf.inputs["Base Color"].default_value = (0.22, 0.075, 0.05, 1.0)\n    bsdf.inputs["Metallic"].default_value = 0.58\n    bsdf.inputs["Roughness"].default_value = 0.26'
    ),
    # 3. Road material
    (
        'bsdf.inputs["Base Color"].default_value = (0.16, 0.17, 0.18, 1.0)\n    bsdf.inputs["Metallic"].default_value = 0.0\n    bsdf.inputs["Roughness"].default_value = 0.68',
        'bsdf.inputs["Base Color"].default_value = (0.09, 0.10, 0.11, 1.0)\n    bsdf.inputs["Metallic"].default_value = 0.0\n    bsdf.inputs["Roughness"].default_value = 0.65'
    ),
    # 4. Lawn & Hedge
    (
        'bsdf.inputs["Base Color"].default_value = (0.13, 0.30, 0.10, 1.0)',
        'bsdf.inputs["Base Color"].default_value = (0.08, 0.22, 0.06, 1.0)'
    ),
    (
        'bsdf.inputs["Base Color"].default_value = (0.16, 0.32, 0.08, 1.0)',
        'bsdf.inputs["Base Color"].default_value = (0.10, 0.25, 0.06, 1.0)'
    ),
    # 5. Sun & Sky
    (
        'sun_data.energy = 4.2\n    sun_data.color = (1.0, 0.97, 0.92)',
        'sun_data.energy = 2.8\n    sun_data.color = (1.0, 0.96, 0.90)'
    ),
    (
        'bg_node.inputs["Strength"].default_value = 1.15',
        'bg_node.inputs["Strength"].default_value = 0.75\n    sky_node.sun_intensity = 0.65\n    sky_node.aerosol_density = 0.35'
    ),
]

for old, new in replacements:
    if old in text:
        text = text.replace(old, new, 1)
        print("Replaced:", old[:30].strip())
    else:
        print("Not found:", old[:30].strip())

with open(script_path, "w", encoding="utf-8") as f:
    f.write(text)

print("Finished applying updates to build_gate_gemini.py")
