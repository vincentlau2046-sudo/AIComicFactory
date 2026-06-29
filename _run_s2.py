#!/usr/bin/env python3
"""Run S2 character extract via Qianfan API"""
import json, sys, urllib.request
sys.path.insert(0, '.')
from core.prompt_runner import run_character_extract
from core.state_manager import get_state_manager

parsed = json.load(open('projects/last_bento/s1_parsed.json'))
print(f'Loaded S1: {len(parsed.get("scenes",[]))} scenes')

result = run_character_extract('projects/last_bento', parsed_script=parsed)
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

with urllib.request.urlopen(req, timeout=300) as resp:
    content = json.loads(resp.read())['choices'][0]['message']['content']

def extract_json(text):
    text = text.strip()
    try: return json.loads(text)
    except: pass
    if '```json' in text:
        block = text.split('```json')[1].split('```')[0]
        try: return json.loads(block.strip())
        except: pass
    start, end = text.find('{'), text.rfind('}')
    if start >= 0 and end > start:
        for t in range(end, max(start, end-5000), -1):
            if text[t] == '}':
                try: return json.loads(text[start:t+1])
                except: continue
    raise ValueError(f'Cannot extract JSON: {text[:200]}')

chars = extract_json(content)
print(f'S2 result: {len(chars.get("characters",[]))} characters')

sm = get_state_manager()
sm.mark_running('last_bento', 's2_character_extract')
with open('projects/last_bento/s2_characters.json', 'w') as f:
    json.dump(chars, f, ensure_ascii=False, indent=2)
sm.mark_completed('last_bento', 's2_character_extract', output='s2_characters.json')
print('S2 done')
