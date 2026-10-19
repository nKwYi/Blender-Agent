import json
import socket
import urllib.error
import urllib.request

from .config import AgentError, get_config
from .state import Err

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "create_primitive",
            "description": "创建一个基础几何体",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["cube", "sphere", "cylinder", "cone", "plane"],
                    },
                    "name": {"type": "string"},
                    "location": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "[x, y, z]，单位米",
                    },
                    "size": {
                        "type": "number",
                        "description": "整体包围盒尺寸，单位米，默认 1.0",
                        "default": 1.0,
                    },
                },
                "required": ["type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_material",
            "description": "给指定物体设置 PBR 材质",
            "parameters": {
                "type": "object",
                "properties": {
                    "object_name": {"type": "string"},
                    "color": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "[R, G, B] 或 [R, G, B, A]，0-1 范围。红色 = [1, 0, 0]",
                    },
                    "metallic": {"type": "number", "default": 0.0},
                    "roughness": {"type": "number", "default": 0.5},
                },
                "required": ["object_name", "color"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "transform_object",
            "description": "移动、旋转或缩放物体，只改给出的分量",
            "parameters": {
                "type": "object",
                "properties": {
                    "object_name": {"type": "string"},
                    "location": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "[x, y, z]，单位米",
                    },
                    "rotation": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "[X, Y, Z] 欧拉角，单位度（旋转 45 度就填 45）",
                    },
                    "scale": {"type": "array", "items": {"type": "number"}},
                },
                "required": ["object_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_scene_info",
            "description": "获取当前场景信息（物体名、类型、位置、是否有材质）",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_blender_code",
            "description": "执行任意 Blender Python 代码（仅在结构化工具不够用时使用）",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "要执行的 Python 代码"},
                },
                "required": ["code"],
            },
        },
    },
]

SYSTEM_PROMPT = (
    "你是专业的 Blender 3D 高保真建模与程序化几何设计助手。根据用户需求生成具有工业级品质与真实物理尺度的场景和资产。\n\n"
    "【核心工作流与工具偏好】\n"
    "1. 所有操作前必须先调用 get_scene_info 检查场景状态（物体名、位置、材质）。\n"
    "2. 工具使用原则：\n"
    "   - 简单的单个基础几何体摆放可使用结构化工具（create_primitive / transform_object / set_material）。\n"
    "   - 对于茶杯、器皿、道具、机械、家具、建筑等复杂造型，严禁粗劣散件拼接（拒绝搭积木拼凑感）！请直接使用 execute_blender_code 编写高质量、参数化的 Blender Python 脚本。直接使用核心 Bmesh/修改器逻辑（建议控制在 50-90 行内完成高精度造型），结构紧凑利落，确保高效生成。\n"
    "3. 工具返回 error 时，认真阅读错误信息并修正后重试，严禁重复同一失败调用。\n"
    "【界面极简输出纪律（重要：面向 Blender 侧边栏紧凑气泡，字字千金）】\n"
    "1. 严禁名词科普与同义词列表：严禁向用户解释'工程上有几个名字'、严禁列举各种行业板材名称对照、严禁科普理论。用户是来建模的，不需要看字典式名词罗列！\n"
    "2. 严禁暴露底层代码、坐标与内部物体名：严禁在向用户回复的文本中暴露类似 'Cube.001 (y≈-6.0)'、'bmesh.ops'、'bpy.data' 等开发细节。直接用自然的工业/视觉语言表述（如'建筑正面外侧'、'深灰金属拉丝'）。\n"
    "3. 绝对严禁输出 Markdown 表格：Blender 侧边栏无法渲染表格，严禁使用任何 '|' 表格语法。\n"
    "4. 追问选项极简（核心约束）：\n"
    "   - 严格只输出：1 句极简开场 + 2-3 个核心细节（格式：1. 细节名：选项A (推荐) / 选项B）；\n"
    "   - 严禁在选项后面输出'回复编号或按推荐，我立刻开始'等任何多余结语（界面已有原生按钮供点击，文字属于纯噪音）。\n"
    "5. 建模完成后极简：仅用 1 句话告知已生成什么模型及新增对象，严禁输出长篇总结报告。\n\n"
    "【几何节点 (Geometry Nodes) 与 BMesh 选型判定矩阵】\n"
    "1. 必须优先使用 几何节点 (Geometry Nodes) 处理的部分：\n"
    "   - 阵列与重复构件：围栏/木栅栏桩、栏杆柱、阶梯踏步、百叶窗、屋顶瓦片、螺钉螺栓、等间距压筋与加强肋（Ribs/Corrugations）；\n"
    "   - 沿路径生成的管线与边框：管道、电缆线、扶手栏杆、收口边框线脚（Curve to Mesh）；\n"
    "   - 表面微细节与散布：草地碎石散布、地面砖缝、微缩场景中的散落小雪堆或松树散布；\n"
    "   - 优势：保持非破坏性、修改器参数可随时调整、高并发实例化性能极高。\n"
    "2. 优先使用 BMesh 传统代码的部分：\n"
    "   - 旋转对称单体器皿：茶杯、花瓶、碗盘（使用 bmesh.ops.spin 一体化车削最简洁直观）；\n"
    "   - 基础主体与引导体量：建筑主墙体、开特定门窗洞。\n"
    "3. 混合管线规范（Hybrid Pipeline）：主体/引导曲线用简单 BMesh/Curve 生成；阵列构件、管道拉伸与表面散布挂载 GeometryNodes 修改器构建。\n"
    "4. Blender 5.x 几何节点 Python 规范（严防 AttributeError 报错）：\n"
    "   - 必须使用 4.0+ 现代化 interface API 声明接口，严禁使用旧版 inputs.new()：\n"
    "     mod = obj.modifiers.new(name='GeometryNodes', type='NODES')\n"
    "     ng = bpy.data.node_groups.new('GN_Setup', 'GeometryNodeTree')\n"
    "     mod.node_group = ng\n"
    "     ng.interface.new_socket('Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')\n"
    "     ng.interface.new_socket('Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')\n"
    "     inp = ng.nodes.new('NodeGroupInput')\n"
    "     outp = ng.nodes.new('NodeGroupOutput')\n"
    "   - 常用节点 ID 名备查：'GeometryNodeInstanceOnPoints', 'GeometryNodeMeshLine', 'GeometryNodeCurveToMesh', 'GeometryNodeCurvePrimitiveCircle', 'GeometryNodeDistributePointsOnFaces', 'GeometryNodeRealizeInstances', 'GeometryNodeJoinGeometry'。\n\n"
    "【智能自适应多轮工作流】\n"
    "1. 简单单一指令（如“建个立方体”、“加个聚光灯”、“移动到原点”）：无需追问，直接调用工具/脚本高效完成建模。\n"
    "2. 产品级/复合型需求（如“茶杯”、“水杯”、“沙发”、“小洋房”、“机械构件”等）：\n"
    "   - 第一步【规格选项推选】：若用户初次输入未指明具体参数，严禁直接生成散乱物体。直接以简练一句话开场（严禁输出任何关于当前场景物体数量、预检分析等冗长废话！），清晰列出 2-4 个核心细节（请使用清晰的编号与斜杠，如：1. 风格：选项A (推荐) / 选项B / 选项C，每题独立一行），并给出明确的括号推荐（如“（推荐：选项A）”或“选项A (推荐)”），供用户在界面上一键点选；\n"
    "   - 第二步【立即建模交付】：一旦用户进行了选择、输入了参数、点击了确认、或指令中包含“开始建模/参数已确认/全部按推荐/按推荐”时，【严禁再次向用户输出复述清单二次追问确认】！必须立即调用 get_scene_info 与 execute_blender_code 编写完整高质量的建模脚本直接在场景中生成模型，建模完成后简述执行步骤与新增组件。\n\n"
    "【严禁粗劣散件堆叠与防穿模规范（拒绝搭积木）】\n"
    "- 一体化成型优先（Lathe/Spin/Continuous Extrude）：茶杯、碗碟、瓶罐等旋转对称器皿，严禁由多个基础几何体堆叠拼凑！首选使用截面曲线 Spin/Screw 旋转车削成型，或单圆柱连续环切、挤出与缩放，一次性生成外壁、内凹腔体、光滑卷唇与圈足底座一体化的连续单网格。\n"
    "- 附件熔接与防内穿（Boolean Union）：把手、提梁、壶嘴等附件必须使用 Boolean(UNION) 与主体熔接为一个整体；把手端面必须紧密咬合杯身外表面，绝对严禁把手网格刺破杯壁穿透至杯腔内部！\n"
    "- 液体与容器防穿模规范（Liquid Inset）：液体网格的外半径必须严格比容器内壁半径缩小 1.0~1.5mm（offset inward 0.001~0.0015m），严禁与容器壁重叠或刺出外壁；液体底面高度必须比杯内底抬高 1mm，严禁共面导致 Z-Fighting 画面闪烁。\n"
    "- 构件装配咬合（Deep Overlap）：复合构件相邻零件接触处相互嵌合 5-15mm，彻底杜绝悬空与无逻辑的内外乱穿。\n\n"
    "【3D 硬表面与几何体建模规范】\n"
    "- 真实尺度感：严格遵循人体工学与物理尺寸（如茶杯口径 8-9cm、高 8cm、壁厚 2.5mm；椅子座高 45cm；建筑层高 3-4m）。坐标单位是米，角度单位是度。\n"
    "- 平滑着色与法线：圆柱、球体及弧面造型必须显式执行 bpy.ops.object.shade_smooth()，消除多边形棱角。\n"
    "- 边缘微倒角：真实物体没有绝对的 0 倒角刀锋边缘，器皿与工业部件添加 Bevel 修改器或倒角线以捕捉高光；薄壁器皿必须添加 Solidify（实体化加厚 2-3mm）。\n"
    "- 坐标规范：创建网格后应用变换 bpy.ops.object.transform_apply(rotation=True, scale=True)。\n\n"
    "【建筑与空间生成规范】\n"
    "- 阶段顺序：地基体量 (Massing) -> 楼板墙体 (Slabs & Walls) -> 立面开窗 (Fenestration) -> 屋顶与收口 (Roof & Details)。\n"
    "- 立面进深阴影（Reveal Depth）：门窗玻璃与外立面绝不能处于同一平面，必须内凹 10-20cm 产生真实建筑投影，窗框加厚 6-8cm。\n"
    "- 结构厚度：外墙厚 0.2-0.3m，楼板厚 0.15-0.2m，平屋顶加 0.9-1.2m 女儿墙，坡屋顶做挑檐。\n\n"
    "【物理真实 PBR 材质规范】\n"
    "在脚本中配置 Principled BSDF 材质节点（color 为 0-1 的 RGB）：\n"
    "- 陶瓷/白瓷：Base Color (0.9, 0.9, 0.9), Roughness 0.06-0.1, Coat 0.3, IOR 1.5。\n"
    "- 玻璃/幕墙：Transmission Weight 1.0, Roughness 0.02, IOR 1.52, Coat 0.3。\n"
    "- 液体/茶水：Transmission Weight 1.0, Roughness 0.01, IOR 1.333，带微色体积吸收。\n"
    "- 建筑混凝土/石材：Base Color 暖/冷浅灰 (0.7, 0.7, 0.7), Roughness 0.75-0.85。\n"
    "- 铝合金/金属构件：Metallic 1.0, Roughness 0.25-0.4, 深灰/黑。\n"
)


def proxy_hint():
    proxies = urllib.request.getproxies()
    target = proxies.get("https") or proxies.get("http")
    return f"（当前走系统代理 {target}，确认它还开着）" if target else ""


def fetch_available_models(api_key, base_url, timeout=10):
    """从 OpenAI 兼容服务商（DeepSeek / MiniMax）获取最新可用模型列表。"""
    if not api_key:
        raise AgentError("缺少 API Key，无法获取模型列表")

    url = base_url.rstrip("/") + "/models"
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": "Bearer " + api_key,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("error", {}).get("message", detail)
        except ValueError:
            pass
        hint = {
            401: "API Key 无效",
            402: "账户余额或 Token Plan 配额不足",
            429: "请求过于频繁",
        }.get(error.code)
        raise AgentError(
            f"获取模型列表失败 HTTP {error.code}{'（' + hint + '）' if hint else ''}：{detail[:300]}",
            error.code,
        )
    except (urllib.error.URLError, socket.timeout, TimeoutError) as error:
        raise AgentError(f"连不上模型服务：{error}{proxy_hint()}", 0)

    try:
        data = json.loads(body)
    except ValueError:
        raise AgentError(f"返回的不是 JSON：{body[:200]}", 200)

    raw_models = []
    if isinstance(data, dict):
        if "data" in data and isinstance(data["data"], list):
            raw_models = [m.get("id") for m in data["data"] if isinstance(m, dict) and m.get("id")]
        elif "models" in data and isinstance(data["models"], list):
            raw_models = [m.get("id") if isinstance(m, dict) else str(m) for m in data["models"]]
    elif isinstance(data, list):
        raw_models = [m.get("id") if isinstance(m, dict) else str(m) for m in data]

    seen = set()
    models = []
    if "minimax" in base_url.lower():
        seen.add("MiniMax-M3.1-Flash-Preview")
        models.append("MiniMax-M3.1-Flash-Preview")

    for m in raw_models:
        if m and m not in seen:
            seen.add(m)
            models.append(m)

    if not models:
        raise AgentError("未解析到任何可用模型标识", 200)
    return models


def chat_completion(messages, tools, *, api_key, model, base_url, timeout):
    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "stream": False,
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
            "Accept-Encoding": "identity",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")
        try:
            detail = json.loads(detail).get("error", {}).get("message", detail)
        except ValueError:
            pass
        hint = {
            401: "API Key 无效",
            402: "账户余额或 Token Plan 配额不足",
            422: "模型名或请求参数不被接受",
            429: "请求过于频繁",
        }.get(error.code)
        tail = proxy_hint() if error.code in (502, 504) else ""
        raise AgentError(
            f"API 服务返回 {error.code}{'（' + hint + '）' if hint else ''}：{detail[:300]}{tail}",
            error.code,
        )
    except (urllib.error.URLError, socket.timeout, TimeoutError) as error:
        kind = "timeout" if isinstance(error, (socket.timeout, TimeoutError)) or "timed out" in str(error).lower() else "unreachable"
        if kind == "timeout":
            raise AgentError(
                f"单次请求超时（已超过 {timeout} 秒）：模型正在深度思考或网络响应缓慢，可在【设置】Tab 调大超时时间{proxy_hint()}",
                0,
                kind,
            )
        raise AgentError(f"连不上 API 服务：{error}{proxy_hint()}", 0, kind)

    try:
        return json.loads(body)
    except ValueError:
        raise AgentError(f"API 服务返回的不是 JSON：{body[:300]}", 200)


def known_tool_names():
    return {t["function"]["name"] for t in TOOLS}


def tools_for(cfg):
    """只声明当前真的注册了、真的能执行的工具。视口截图回传未接通（无法验证
    deepseek-flash 接受图像输入），所以这里不报这个能力，界面上也不给开关。"""
    return list(TOOLS)


def system_prompt(cfg):
    text = SYSTEM_PROMPT
    if not cfg.get("allow_arbitrary_code"):
        text += " execute_blender_code 属高风险操作，需要用户在面板里明确批准，被拒绝时不要重复请求。"
    text += " 你看不到画面，不要声称你看见了视口。"
    return text


def classify(error):
    from .config import AgentError
    if not isinstance(error, AgentError):
        return Err.INTERNAL
    if error.kind == "timeout":
        return Err.TIMEOUT
    status = error.status
    if status == 401:
        return Err.KEY_INVALID
    if status == 402:
        return Err.BILLING
    if status == 0:
        return Err.NET
    if status == 200:
        return Err.BAD_RESPONSE
    return Err.NET_HTTP


def agent_loop(user_message, *, chat=None, config=None):
    """同步入口（无头测试与降级路径用）。真实实现与 GUI 走同一个 worker_loop。"""
    from .worker import Controller
    cfg = dict(config) if config else get_config()
    if chat:
        cfg["chat"] = chat
    if not cfg.get("api_key"):
        from .config import KEY_MISSING
        raise AgentError(KEY_MISSING)
    ctrl = Controller()
    ctrl.start(user_message, cfg)
    while ctrl.tick():
        pass
    run = ctrl.run
    return {
        "reply": run.reply,
        "rounds": run.rounds,
        "calls": [{"name": c.name, "ok": c.ok, "result": c.result} for c in run.calls],
        "usage": run.usage,
        "elapsed": run.elapsed,
        "phase": run.phase.value,
        "error": run.err.value,
        "detail": run.detail,
        "truncated": run.err in (Err.BUDGET_ROUNDS, Err.BUDGET_WALL),
    }
