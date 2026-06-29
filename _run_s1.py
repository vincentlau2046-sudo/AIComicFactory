#!/usr/bin/env python3
"""Run S1 script parse via Qianfan API"""
import json, sys, urllib.request
sys.path.insert(0, '.')
from core.prompt_runner import run_script_parse
from core.state_manager import get_state_manager

source = open('projects/last_bento/source.txt').read()
print(f'Source: {len(source)} chars')

result = run_script_parse('projects/last_bento', source)
print(f'Prompt: {len(result["messages"])} messages')

config = json.load(open('/home/vince/.openclaw/agents/main/agent/models.json'))
key = config['providers']['baidu-codingplan']['apiKey']

payload = json.dumps({
    'model': 'glm-5.1',
    'messages': result['messages'],
    'temperature': 0.3,
    'max_tokens': 8192,
}).encode()

req = urllib.request.Request(
    'https://qianfan.baidubce.com/v2/coding/chat/completions',
    data=payload,
    headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'},
    method='POST',
)

with urllib.request.urlopen(req, timeout=300) as resp:
    api_result = json.loads(resp.read())
    content = api_result['choices'][0]['message']['content']

def extract_json(text):
    text = text.strip()
    try: return json.loads(text)
    except: pass
    if '```json' in text:
        block = text.split('```json')[1].split('```')[0]
        try: return json.loads(block.strip())
        except: pass
    start = text.find('{')
    end = text.rfind('}')
    if start >= 0 and end > start:
        for trunc_end in range(end, max(start, end-5000), -1):
            if text[trunc_end] == '}':
                try: return json.loads(text[start:trunc_end+1])
                except: continue
    raise ValueError(f'Cannot extract JSON: {text[:200]}')

parsed = extract_json(content)
print(f'S1 result: {len(parsed.get("scenes",[]))} scenes')

sm = get_state_manager()
sm.init_project('last_bento')
sm.mark_running('last_bento', 's1_parse')

with open('projects/last_bento/s1_parsed.json', 'w') as f:
    json.dump(parsed, f, ensure_ascii=False, indent=2)

sm.mark_completed('last_bento', 's1_parse', output='s1_parsed.json')
print('S1 done')
