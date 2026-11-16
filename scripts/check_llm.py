"""Check the language model set in .env: reachable, supports tool calling, and speed.

Usage (from the project folder):  python scripts/check_llm.py
"""
import json
import os
import sys
import time

import httpx

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

for line in open(os.path.join(ROOT, ".env"), encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

base = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:11434/v1").rstrip("/")
model = os.environ.get("LLM_MODEL", "qwen2.5:7b")
tool = {"type": "function", "function": {
    "name": "get_library_info", "description": "Library hours, rules and services.",
    "parameters": {"type": "object", "properties": {"topic": {"type": "string"}}}}}

print(f"Model {model} at {base}")
t0 = time.time()
try:
    r = httpx.post(f"{base}/chat/completions", timeout=600,
                   headers={"Authorization": f"Bearer {os.environ.get('LLM_API_KEY', 'ollama')}"},
                   json={"model": model, "tools": [tool], "messages": [
                       {"role": "system", "content": "You are a library guide. Use tools for library facts."},
                       {"role": "user", "content": "What are the library opening hours?"}]})
    r.raise_for_status()
except httpx.HTTPError as e:
    sys.exit(f"[FAIL] Could not reach the model: {e}")
secs = time.time() - t0
msg = r.json()["choices"][0]["message"]
calls = msg.get("tool_calls") or []
print(f"[{'OK  ' if calls else 'FAIL'}] Tool calling: "
      + (f"called {calls[0]['function']['name']}" if calls else "model answered without calling the tool"))
verdict = "good" if secs < 15 else "usable" if secs < 45 else "too slow for students"
print(f"[{'OK  ' if secs < 45 else 'SLOW'}] First step took {secs:.0f} s ({verdict}). "
      "A full reply usually needs 2-3 such steps.")
sys.exit(0 if calls and secs < 45 else 1)
