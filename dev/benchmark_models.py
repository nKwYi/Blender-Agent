import time
import json
import urllib.request
from bl_ext.user_default.blender_deepseek_agent import config, agent

cfg = config.get_config()
api_key = cfg['api_key']

models = ['MiniMax-M3', 'MiniMax-M3.1-Flash-Preview', 'deepseek-chat']

for m in ['MiniMax-M3', 'MiniMax-M3.1-Flash-Preview']:
    print(f"\n--- Testing {m} without tools ---")
    payload = {
        'model': m,
        'messages': [
            {'role': 'user', 'content': '写一段 Blender Python 脚本创建一个茶杯'}
        ],
        'stream': False
    }
    req = urllib.request.Request(
        'https://api.minimax.cn/v1/chat/completions',
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + api_key}
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        dt = time.time() - t0
        content = data['choices'][0]['message'].get('content', '')
        print(f"SUCCESS in {dt:.2f}s! Length: {len(content)}")
    except Exception as e:
        print(f"FAILED in {time.time()-t0:.2f}s: {e}")
