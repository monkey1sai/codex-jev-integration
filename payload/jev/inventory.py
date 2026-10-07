"""Local-only inventory. Runtime availability is caller-reported, never discovered.

Only ``candidates`` may enter an authorized provider request. Bindings and
provenance are local metadata; existence is neither suitability nor permission.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys

MAX_SKILL_BYTES = 256 * 1024
MAX_INPUT_BYTES = 1024 * 1024
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}")


class InventoryFailure(ValueError):
    """Fixed nonsensitive failure code."""


def _text(value, limit=2000):
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise InventoryFailure("INVALID_INVENTORY_SPEC")
    return value


def _ids(values):
    if type(values) not in (list, tuple) or len(values) > 24:
        raise InventoryFailure("INVALID_RESOURCE_IDS")
    if any(type(x) is not str or x == 'none' or not ID.fullmatch(x) for x in values):
        raise InventoryFailure("INVALID_RESOURCE_IDS")
    if len(set(values)) != len(values):
        raise InventoryFailure("DUPLICATE_RESOURCE_IDS")
    return list(values)


def _strings(values):
    if type(values) is not list or len(values) > 8:
        raise InventoryFailure("INVALID_INVENTORY_SPEC")
    return [_text(x, 500) for x in values]


def _utc(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.utcoffset() is None or result.utcoffset().total_seconds() != 0:
            raise ValueError
        return result
    except (AttributeError, TypeError, ValueError):
        raise InventoryFailure("INVALID_SNAPSHOT_TIME") from None


def _unsafe(info):
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _skill(binding):
    """Read one explicit canonical file, with bounds and link checks; no traversal scan."""
    # Reject network/device namespaces before any filesystem probe can cause SMB IO.
    if binding.startswith(('\\\\', '//')):
        return False, None, 'NONLOCAL_SKILL_BINDING'
    if os.name == 'nt':
        if not re.match(r'^[A-Za-z]:[\\/]', binding):
            return False, None, 'NONLOCAL_SKILL_BINDING'
        import ctypes
        drive_type = ctypes.windll.kernel32.GetDriveTypeW
        drive_type.argtypes = [ctypes.c_wchar_p]
        drive_type.restype = ctypes.c_uint
        if drive_type(str(binding[:3])) not in (2, 3, 6):
            return False, None, 'NONLOCAL_SKILL_BINDING'
    path = Path(binding)
    if not path.is_absolute() or path.name != "SKILL.md" or ".." in path.parts:
        return False, None, "INVALID_SKILL_BINDING"
    try:
        for component in (*reversed(path.parents), path):
            if _unsafe(component.lstat()):
                return False, None, "UNSAFE_SKILL_BINDING"
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            return False, None, "INVALID_SKILL_FILE"
        if before.st_size > MAX_SKILL_BYTES:
            return False, None, "SKILL_TOO_LARGE"
        if str(path.resolve(strict=True)) != str(path):
            return False, None, "NONCANONICAL_SKILL_BINDING"
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if _unsafe(opened) or not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or (
                before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                return False, None, "SKILL_CHANGED"
            raw = stream.read(MAX_SKILL_BYTES + 1)
            after = os.fstat(stream.fileno())
        final = path.lstat()
        if len(raw) > MAX_SKILL_BYTES:
            return False, None, "SKILL_TOO_LARGE"
        if _unsafe(final) or final.st_nlink != 1 or (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
            final.st_dev, final.st_ino, final.st_size, final.st_mtime_ns) or (
            opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            return False, None, "SKILL_CHANGED"
        return True, hashlib.sha256(raw).hexdigest(), None
    except (OSError, RuntimeError, ValueError):
        return False, None, "SKILL_UNREADABLE"


def build_inventory(snapshot, specs, required_ids=(), now=None):
    """Build bounded candidates; this API cannot read the Codex runtime itself.

    ``available`` supplied in specs is ignored. Descriptions/criteria must be
    caller-sanitized. required unavailable/out-of-scope resources are retained
    for a visible fallback, never silently replaced. No files are written.
    """
    if type(snapshot) is not dict or snapshot.get("provenance") != "caller_runtime":
        raise InventoryFailure("INVALID_RUNTIME_SNAPSHOT")
    captured = _utc(snapshot.get("captured_at"))
    current = datetime.now(timezone.utc) if now is None else (_utc(now) if isinstance(now, str) else now)
    if not isinstance(current, datetime) or current.utcoffset() is None:
        raise InventoryFailure("INVALID_CURRENT_TIME")
    age = (current - captured).total_seconds()
    if age > 300 or age < -5:
        raise InventoryFailure("STALE_RUNTIME_SNAPSHOT" if age > 300 else "FUTURE_RUNTIME_SNAPSHOT")
    tools = snapshot.get("tools")
    if type(tools) is not list or len(tools) > 4096 or any(
        type(x) is not str or not x.strip() or len(x) > 256 for x in tools) or len(set(tools)) != len(tools):
        raise InventoryFailure("INVALID_RUNTIME_TOOLS")
    if type(specs) is not list or len(specs) > 24:
        raise InventoryFailure("INVALID_INVENTORY_SPECS")
    required = _ids(required_ids)
    rows, bindings, skill_hashes, exclusions, all_rows = [], {}, {}, [], []
    keys = {}
    for item in specs:
        if type(item) is not dict:
            raise InventoryFailure("INVALID_INVENTORY_SPEC")
        resource_id = _ids([item.get("id")])[0]
        if resource_id in bindings:
            raise InventoryFailure("DUPLICATE_RESOURCE_ID")
        kind, binding = item.get("kind"), _text(item.get("binding"), 4096)
        if kind not in ("tool", "mcp", "skill") or type(item.get("in_scope")) is not bool:
            raise InventoryFailure("INVALID_INVENTORY_SPEC")
        available, digest, reason = (_skill(binding) if kind == "skill" else
            (binding in tools, None, None if binding in tools else "TOOL_NOT_IN_SNAPSHOT"))
        row = {"id": resource_id, "kind": kind, "description": _text(item.get("description"), 240),
               "available": available, "in_scope": item["in_scope"],
               "when_to_use": _text(item.get("when_to_use"), 1000), "limits": _strings(item.get("limits")),
               "requires": _ids(item.get("requires")), "conflicts": _ids(item.get("conflicts"))}
        bindings[resource_id] = binding
        all_rows.append(row)
        if digest:
            skill_hashes[resource_id] = digest
        key = item.get("capability_key")
        if key is not None:
            keys[resource_id] = _text(key, 128)
        if not available or not row["in_scope"]:
            exclusions.append({"id": resource_id, "reason": reason if not available else "OUT_OF_SCOPE"})
            if resource_id not in required:
                continue
        rows.append(row)
    if any(x not in bindings for x in required):
        raise InventoryFailure("UNKNOWN_REQUIRED_RESOURCE")
    if any(x not in bindings for row in all_rows for x in row["requires"] + row["conflicts"]):
        raise InventoryFailure("UNKNOWN_RESOURCE_REFERENCE")
    kept = []
    for row in rows:
        key = keys.get(row["id"])
        peers = [x for x in rows if key is not None and keys.get(x["id"]) == key]
        must = [x for x in peers if x["id"] in required]
        winner = must[0] if must else (peers[0] if peers else row)
        if row["id"] in required or row is winner:
            kept.append(row)
        else:
            exclusions.append({"id": row["id"], "reason": "DUPLICATE_CAPABILITY"})
    unavailable = [x["id"] for x in kept if x["id"] in required and (not x["available"] or not x["in_scope"])]
    present = {x["id"] for x in kept}
    missing_dependencies = [{"id": x["id"], "requires": [r for r in x["requires"] if r not in present]}
                            for x in kept if any(r not in present for r in x["requires"])]
    missing_conflicts = [{"id": x["id"], "conflicts": [r for r in x["conflicts"] if r not in present]}
                         for x in kept if any(r not in present for r in x["conflicts"])]
    # Removing an unavailable/duplicate target must remain visible. The caller
    # must repair this inventory before provider submission, not erase requires.
    reasons = (["REQUIRED_RESOURCE_UNAVAILABLE"] if unavailable else [])
    if missing_dependencies:
        reasons.append("RESOURCE_DEPENDENCY_UNAVAILABLE")
    if missing_conflicts:
        reasons.append("RESOURCE_CONFLICT_REFERENCE_EXCLUDED")
    normalized = {"captured_at": captured.isoformat(), "tools": sorted(tools), "provenance": "caller_runtime"}
    return {"candidates": kept, "required_ids": required, "fallback": bool(reasons),
            "reasons": reasons,
            "local_bindings": {x["id"]: bindings[x["id"]] for x in kept},
            "provenance": {"availability": "caller_reported", "runtime_source": "caller_runtime",
                "api_can_read_runtime": False, "captured_at": captured.isoformat(),
                "snapshot_sha256": hashlib.sha256(json.dumps(normalized, sort_keys=True).encode()).hexdigest(),
                "skill_sha256": skill_hashes, "excluded": exclusions,
                "missing_dependencies": missing_dependencies,
                "missing_conflicts": missing_conflicts,
                "required_unavailable": unavailable, "execution_verified": False}}


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            raise InventoryFailure("INPUT_TOO_LARGE")
        args = json.loads(raw)
        if type(args) is not dict or set(args) - {"snapshot", "specs", "required_ids"}:
            raise InventoryFailure("INVALID_ARGUMENTS")
        result = build_inventory(**args)
    except (InventoryFailure, ValueError, TypeError):
        # Parser/argument details can contain private bindings; never echo them.
        result = {"status": "fallback", "reason": "INVALID_INVENTORY_INPUT", "provider_called": False}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
