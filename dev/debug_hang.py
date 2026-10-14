import time
import json
import urllib.request
import sys
from bl_ext.user_default.blender_deepseek_agent import config, agent

sys.stdout.reconfigure(line_buffering=True)
cfg = config.get_config()
api_key = cfg['api_key']

prompt = '创建一个茶杯'
messages = [
    {'role': 'system', 'content': agent.system_prompt(cfg)},
    {'role': 'user', 'content': prompt},
    {'role': 'assistant', 'content': '我先看一下当前场景状态。', 'tool_calls': [{'id': 'call_1', 'type': 'function', 'function': {'name': 'get_scene_info', 'arguments': '{}'}}]},
    {'role': 'tool', 'tool_call_id': 'call_1', 'content': json.dumps({'objects': [{'name': 'Cube', 'type': 'MESH'}]})}
]

payload = {
    'model': cfg['model'],
    'messages': messages,
    'tools': agent.tools_for(cfg),
    'tool_choice': 'auto',
    'stream': False
}

print(f"Testing model: {cfg['model']}")
print(f"Payload size: {len(json.dumps(payload))} bytes")

req = urllib.request.Request(
    cfg['base_url'].rstrip('/') + '/chat/completions',
    data=json.dumps(payload).encode('utf-8'),
    headers={
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + api_key,
        'Accept-Encoding': 'identity'
    }
)

t0 = time.time()
print("Starting request...")
try:
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = resp.read().decode('utf-8')
        dt = time.time() - t0
        print(f"SUCCESS in {dt:.2f}s! Status: {resp.status}, Body len: {len(body)}")
        data = json.loads(body)
        print("Choice:", json.dumps(data['choices'][0], ensure_ascii=False)[:300])
except Exception as e:
    print(f"FAILED in {time.time()-t0:.2f}s: {e}")
