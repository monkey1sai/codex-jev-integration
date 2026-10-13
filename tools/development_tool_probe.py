"""Fixed zero-provider inventory, run through native command/exec, never installs."""
import hashlib
import json
import os
from pathlib import Path
import shutil

TOOLS = ('bash', 'rg', 'grep', 'find', 'cat', 'python', 'python3', 'node', 'git')


def inventory():
    result = {}
    for name in TOOLS:
        found = shutil.which(name)
        path = Path(found).resolve() if found else None
        result[name] = {'status': 'AVAILABLE' if path else 'MISSING',
                        'path': str(path) if path else None,
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest() if path else None}
    return {'version': 1, 'cwd': os.getcwd(), 'path': os.environ.get('PATH'), 'tools': result}


if __name__ == '__main__':
    print(json.dumps(inventory(), sort_keys=True))
