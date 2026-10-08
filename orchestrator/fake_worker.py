"""Synthetic local worker. It never calls a model or executes supplied code."""
import argparse
import json
from pathlib import Path
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--behavior", choices=("valid", "bad", "scope", "hang", "overflow"), default="valid")
    parser.add_argument("--delay", type=float, default=0.15)
    args = parser.parse_args()
    task = json.loads(sys.stdin.buffer.read(16385))
    if args.behavior == "hang":
        time.sleep(60)
    if args.behavior == "overflow":
        sys.stdout.write("x" * (3 * 1024 * 1024))
        return
    time.sleep(args.delay)
    numbers = task["inputs"]["numbers"]
    file = Path(task["allowed_files"][0])
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps({"sum": sum(numbers) + (1 if args.behavior == "bad" else 0),
                                "count": len(numbers)}), encoding="utf-8")
    if args.behavior == "scope":
        Path("unexpected.txt").write_text("synthetic scope violation", encoding="utf-8")
    print(json.dumps({"type": "fixture.completed", "task_id": task["task_id"]}))


if __name__ == "__main__":
    main()
