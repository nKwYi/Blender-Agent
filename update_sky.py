import os

script_path = r"E:\Three JS\园区建设\AI大门装饰建模\Gemini版本\build_gate_gemini.py"
with open(script_path, "r", encoding="utf-8") as f:
    text = f.read()

# Let's replace setup_lighting with a rich architectural sky and enhanced sun
old_lighting = """def setup_lighting():
    light_col = bpy.data.collections.new("COL_Lighting")
    bpy.context.scene.collection.children.link(light_col)

    # 1. World Sky Gradient
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new('World')
        bpy.context.scene.world = world
    w_nodes = world.node_tree.nodes
    w_links = world.node_tree.links
    w_nodes.clear()

    bg_node = w_nodes.new("ShaderNodeBackground")
    output_node = w_nodes.new("ShaderNodeOutputWorld")
    w_links.new(bg_node.outputs["Background"], output_node.inputs["Surface"])

    # Architectural Sky Texture (Nishita physical sun/sky simulation)
    sky_node = w_nodes.new("ShaderNodeTexSky")
    sky_node.sky_type = "MULTIPLE_SCATTERING"
    sky_node.sun_elevation = math.radians(42.0)
    sky_node.sun_rotation = math.radians(135.0)
    sky_node.altitude = 50.0
    sky_node.air_density = 1.0
    sky_node.aerosol_density = 0.35
    sky_node.ozone_density = 2.0
    sky_node.sun_intensity = 0.65
    w_links.new(sky_node.outputs["Color"], bg_node.inputs["Color"])
    bg_node.inputs["Strength"].default_value = 0.75"""

new_lighting = """def setup_lighting():
    light_col = bpy.data.collections.new("COL_Lighting")
    bpy.context.scene.collection.children.link(light_col)

    # 1. World Sky Gradient (Rich Architectural Azure Blue Sky)
    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new('World')
        bpy.context.scene.world = world
    w_nodes = world.node_tree.nodes
    w_links = world.node_tree.links
    w_nodes.clear()

    bg_node = w_nodes.new("ShaderNodeBackground")
    output_node = w_nodes.new("ShaderNodeOutputWorld")
    w_links.new(bg_node.outputs["Background"], output_node.inputs["Surface"])

    # Rich Sky Color Ramp (Deep Azure zenith to warm cyan-white horizon)
    tex_coord = w_nodes.new("ShaderNodeTexCoord")
    mapping = w_nodes.new("ShaderNodeMapping")
    mapping.inputs["Rotation"].default_value = (0, math.radians(-15), 0)
    w_links.new(tex_coord.outputs["Generated"], mapping.inputs["Vector"])

    ramp = w_nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = 0.42
    ramp.color_ramp.elements[0].color = (0.75, 0.86, 0.96, 1.0) # Horizon warm sky
    ramp.color_ramp.elements[1].position = 0.88
    ramp.color_ramp.elements[1].color = (0.16, 0.42, 0.78, 1.0) # Zenith deep azure blue
    w_links.new(mapping.outputs["Vector"], ramp.inputs["Fac"])
    w_links.new(ramp.outputs["Color"], bg_node.inputs["Color"])
    bg_node.inputs["Strength"].default_value = 1.25"""

if old_lighting in text:
    text = text.replace(old_lighting, new_lighting, 1)
    print("Replaced lighting with rich azure architectural sky.")
else:
    print("Old lighting block not found, attempting partial match...")
    # Find def setup_lighting():
    idx = text.find("def setup_lighting():")
    idx2 = text.find("    # 2. Key Sun Light", idx)
    if idx != -1 and idx2 != -1:
        text = text[:idx] + new_lighting + "\n\n" + text[idx2:]
        print("Successfully replaced lighting block via index slicing!")

with open(script_path, "w", encoding="utf-8") as f:
    f.write(text)

print("Saved build_gate_gemini.py")
