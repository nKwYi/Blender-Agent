import time
import json
import urllib.request
import sys
from bl_ext.user_default.blender_deepseek_agent import config

sys.stdout.reconfigure(line_buffering=True)
cfg = config.get_config()
api_key = cfg['api_key']

concise_prompt = (
    "你是专业的 Blender 3D 高保真建模助手。根据需求生成具工业级品质的几何资产。\n\n"
    "【工作流】\n"
    "1. 优先调用 get_scene_info 检查场景。\n"
    "2. 对器皿、道具、家具、建筑等造型，使用 execute_blender_code 编写参数化 Python 脚本。"
    "编写代码时保持紧凑高效（40-80行核心逻辑），直接使用 BMesh/修改器成型，避免冗余展开。\n"
    "3. 真实物理尺寸（米），弧面执行 shade_smooth()，薄壁器皿加 Solidify 与 Bevel 倒角。\n"
    "4. 真实 PBR 材质：白瓷(粗糙0.08/清漆0.3)，玻璃(透射1.0/粗糙0.02)，液体(透射1.0/IOR 1.333)。\n"
)

prompt = '创建一个茶杯'
messages = [
    {'role': 'system', 'content': concise_prompt},
    {'role': 'user', 'content': prompt},
    {'role': 'assistant', 'content': '我先看一下当前场景状态。', 'tool_calls': [{'id': 'call_1', 'type': 'function', 'function': {'name': 'get_scene_info', 'arguments': '{}'}}]},
    {'role': 'tool', 'tool_call_id': 'call_1', 'content': json.dumps({'objects': [{'name': 'Cube', 'type': 'MESH'}]})}
]

payload = {
    'model': cfg['model'],
    'messages': messages,
    'tools': [
        {
            'type': 'function',
            'function': {
                'name': 'execute_blender_code',
                'description': '执行 Blender Python 脚本',
                'parameters': {
                    'type': 'object',
                    'properties': {'code': {'type': 'string', 'description': 'Python 代码'}},
                    'required': ['code']
                }
            }
        }
    ],
    'tool_choice': 'auto',
    'stream': False
}

req = urllib.request.Request(
    cfg['base_url'].rstrip('/') + '/chat/completions',
    data=json.dumps(payload).encode('utf-8'),
    headers={
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + api_key,
        'Accept-Encoding': 'identity'
    }
)

print("Starting request with concise prompt...")
t0 = time.time()
try:
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = resp.read().decode('utf-8')
        dt = time.time() - t0
        print(f"SUCCESS in {dt:.2f}s! Status: {resp.status}, Body len: {len(body)}")
        data = json.loads(body)
        print("Choice:", json.dumps(data['choices'][0], ensure_ascii=False)[:300])
except Exception as e:
    print(f"FAILED in {time.time()-t0:.2f}s: {e}")
