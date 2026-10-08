"""Fixed synthetic worker; no dynamic commands or model calls."""
import json
import sys
import time
from pathlib import Path

task = json.load(sys.stdin)
if '--timeout' in sys.argv:
    time.sleep(30)
for name in task['allowed_files']:
    path = Path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"answer":42}\n', encoding='utf-8')
