#!/usr/bin/env python3
"""Robust JSON extraction from LLM output"""
import json, re

def extract_json_robust(text):
    """Extract JSON from LLM response with maximum robustness."""
    text = text.strip()

    # Direct parse
    try: return json.loads(text)
    except: pass

    # ```json ... ```
    if '```json' in text:
        block = text.split('```json')[1].split('```')[0]
        try: return json.loads(block.strip())
        except: pass

    # Find outermost { ... }
    start = text.find('{')
    end = text.rfind('}')
    if start >= 0 and end > start:
        candidate = text[start:end+1]
        try: return json.loads(candidate)
        except: pass
        # Try truncation from end
        for t in range(end, max(start, end-10000), -1):
            if text[t] == '}':
                try: return json.loads(text[start:t+1])
                except: continue

    # Fix unquoted string values: "key":value → "key":"value"
    if start >= 0:
        candidate = text[start:end+1]
        fixed = re.sub(r'("[^"]+")\s*:\s*([^"\s\[\{][^,\}\]]*?)(\s*[,}\]])', r'\1: "\2"\3', candidate)
        # Fix double-quoted endings: ...text"" → ...text"
        fixed = re.sub(r'""(\s*[,}\]])', r'"\1', fixed)
        # Fix number values that got over-quoted: "sceneNumber": "1" → "sceneNumber": 1
        fixed = re.sub(r'"(sceneNumber|shotNumber|duration|startRatio|endRatio)":\s*"(\d+(?:\.\d+)?)"', r'"\1": \2', fixed)
        try: return json.loads(fixed)
        except: pass

    raise ValueError(f'Cannot extract JSON (first 300): {text[:300]}')
