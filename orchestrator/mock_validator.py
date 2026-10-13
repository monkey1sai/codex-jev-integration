"""Controller synthetic oracle used only by offline execution evidence."""
import json
from pathlib import Path
import sys
import time

if '--timeout' in sys.argv:
    time.sleep(30)
if '--fail' in sys.argv:
    raise SystemExit(7)
files = list(Path('.').glob('result*.json'))
if not files:
    raise SystemExit(2)
for path in files:
    value = json.loads(path.read_bytes())
    if type(value) is not dict or set(value) != {'answer'} or type(value['answer']) is not int or value['answer'] != 42:
        raise SystemExit(3)
print('OFFLINE_DATA_VALIDATION_OK')
