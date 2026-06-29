#!/usr/bin/env python3
"""Run S4 shot split via Qianfan API"""
import json, sys, urllib.request
sys.path.insert(0, '.')
from core.prompt_runner import run_shot_split
from core.state_manager import get_state_manager
from _json_utils import extract_json_robust

parsed = json.load(open('projects/last_bento/s1_parsed.json'))
chars_data = json.load(open('projects/last_bento/s2_characters.json'))
characters = chars_data.get('characters', [])
print(f'Loaded: {len(parsed.get("scenes",[]))} scenes, {len(characters)} characters')

result = run_shot_split('projects/last_bento', parsed_script=parsed, characters=characters)
print(f'Prompt: {len(result["messages"])} messages')

config = json.load(open('/home/vince/.openclaw/agents/main/agent/models.json'))
key = config['providers']['baidu-codingplan']['apiKey']

payload = json.dumps({
    'model': 'glm-5.1', 'messages': result['messages'],
    'temperature': 0.3, 'max_tokens': 8192,
}).encode()

req = urllib.request.Request(
    'https://qianfan.baidubce.com/v2/coding/chat/completions',
    data=payload, headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'},
    method='POST',
)

with urllib.request.urlopen(req, timeout=600) as resp:
    content = json.loads(resp.read())['choices'][0]['message']['content']



shots = extract_json_robust(content)
total = sum(len(s.get('shots',[])) for s in shots.get('scenes',[]))
print(f'S4 result: {len(shots.get("scenes",[]))} scenes, {total} shots')

sm = get_state_manager()
sm.mark_running('last_bento', 's4_shot_split')
with open('projects/last_bento/s4_shots.json', 'w') as f:
    json.dump(shots, f, ensure_ascii=False, indent=2)
sm.mark_completed('last_bento', 's4_shot_split', output='s4_shots.json')
print('S4 done')
