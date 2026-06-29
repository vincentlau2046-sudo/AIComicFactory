#!/usr/bin/env python3
"""S4: 分场景逐个处理，避免超时"""
import json, sys, urllib.request
sys.path.insert(0, '.')
from core.state_manager import get_state_manager
from _json_utils import extract_json_robust

parsed = json.load(open('projects/last_bento/s1_parsed.json'))
chars_data = json.load(open('projects/last_bento/s2_characters.json'))
characters = chars_data.get('characters', [])

config = json.load(open('/home/vince/.openclaw/agents/main/agent/models.json'))
key = config['providers']['baidu-codingplan']['apiKey']

def call_api(messages, max_tokens=8192):
    payload = json.dumps({
        'model': 'glm-5.1', 'messages': messages,
        'temperature': 0.3, 'max_tokens': max_tokens,
    }).encode()
    req = urllib.request.Request(
        'https://qianfan.baidubce.com/v2/coding/chat/completions',
        data=payload, headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'},
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read())['choices'][0]['message']['content']

# Build a simpler prompt - just ask for shot list, not full detail
scene_descs = []
for i, scene in enumerate(parsed.get('scenes', [])):
    scene_descs.append(f"Scene {i+1}: {scene.get('setting','')} - {scene.get('description','')[:200]}")

char_descs = [f"{c['name']}: {c.get('visualHint','')}" for c in characters]

system_prompt = """You are a professional anime storyboard artist. Given scenes and characters, create a shot list.
Output ONLY valid JSON in this exact format:
{
  "scenes": [
    {
      "sceneNumber": 1,
      "setting": "description",
      "shots": [
        {
          "shotNumber": 1,
          "prompt": "detailed visual description for image generation",
          "characters": ["name1"],
          "cameraDirection": "medium shot / close-up / wide shot",
          "motionScript": "brief motion description",
          "dialogue": "any dialogue or empty string",
          "transition": "cut / dissolve / fade_in",
          "durationSeconds": 5
        }
      ]
    }
  ]
}

Rules:
- 2-5 shots per scene, keep total under 15 shots
- Each shot 4-8 seconds
- Include establishing shots and close-ups
- motionScript: describe camera movement or character action"""

user_prompt = f"""Characters: {', '.join(char_descs)}

Scenes:
{chr(10).join(scene_descs)}

Create the shot list."""

messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": user_prompt},
]

print(f'Calling API for S4 ({len(user_prompt)} chars prompt)...')
content = call_api(messages, max_tokens=8192)
print(f'Response: {len(content)} chars')

shots = extract_json_robust(content)
total = sum(len(s.get('shots',[])) for s in shots.get('scenes',[]))
print(f'S4 result: {len(shots.get("scenes",[]))} scenes, {total} shots')

sm = get_state_manager()
sm.mark_running('last_bento', 's4_shot_split')
with open('projects/last_bento/s4_shots.json', 'w') as f:
    json.dump(shots, f, ensure_ascii=False, indent=2)
sm.mark_completed('last_bento', 's4_shot_split', output='s4_shots.json')
print('S4 done')
