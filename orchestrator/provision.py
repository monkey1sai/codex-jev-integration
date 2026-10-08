"""Exact-target repo configuration plans; no native config or script execution."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import uuid

from .contracts import ContractError, fingerprint
from .policy import VERSION, compile_policy, load, merge, safe_path, validate_jev, validate_overlay

TARGETS = (".codex/orchestrator.json", ".codex/jev.json")


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_hash(path):
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def external_directory(path, root):
    path = Path(path).absolute()
    for node in [path, *path.parents]:
        if node.is_symlink() or node.is_junction():
            raise ContractError("REPARSE_PATH")
    if path.resolve().is_relative_to(Path(root).resolve()):
        raise ContractError("CONTROLLER_DIRECTORY_OUTSIDE_ROOT_REQUIRED")
    return path


def proposal(repo, spec):
    if type(spec) is not dict or set(spec) != {"orchestrator", "jev"}:
        raise ContractError("SETUP_SPEC")
    validate_overlay(spec["orchestrator"])
    validate_jev(spec["jev"])
    result = []
    for relative, section in zip(TARGETS, ("orchestrator", "jev")):
        path = safe_path(repo, relative)
        current, before_hash = load(path) if path.exists() else ({}, None)
        if section == "orchestrator":
            value = merge(current, spec[section])
        else:
            validate_jev(current)
            value = {**current, **spec[section]}
            if "observability" in spec[section]:
                value["observability"] = {**current.get("observability", {}), **spec[section]["observability"]}
            validate_jev(value)
        result.append({"relative": relative, "before_sha256": before_hash,
                       "after_sha256": sha(encoded(value)), "value": value})
    defaults, _ = load(Path(__file__).with_name("defaults.json"))
    effective = merge(defaults, result[0]["value"])
    for cap in effective["capabilities"].values():
        if set(cap["validators"]) - set(effective["validators"]):
            raise ContractError("UNKNOWN_VALIDATOR")
    return result


def plan(repo, spec):
    repo = Path(repo).absolute()
    if not (repo / ".git").exists():
        raise ContractError("GIT_REPO_REQUIRED")
    files = proposal(repo, spec)
    return {"schema_version": 1, "core_version": VERSION,
            "repo": str(repo.resolve()), "created_at": datetime.now(timezone.utc).isoformat(),
            "spec": deepcopy(spec), "files": files,
            "policy_before": compile_policy(repo)["policy_hash"],
            "defaults_sha256": file_hash(Path(__file__).with_name("defaults.json"))}


def write_new(path, value):
    path = Path(path)
    for node in [path, *path.parents]:
        if node.is_symlink() or node.is_junction():
            raise ContractError("REPARSE_PATH")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(encoded(value))
    return sha(encoded(value))


def replace(path, data):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def apply(repo, plan_path, expected_sha256, journal):
    """Per-file atomicity, not a multi-file OS transaction. Journal survives failure."""
    repo = Path(repo).absolute()
    payload, digest = load(plan_path, max_bytes=262144)
    keys = {"schema_version", "core_version", "repo", "created_at", "spec", "files", "policy_before", "defaults_sha256"}
    if digest != expected_sha256 or type(payload) is not dict or set(payload) != keys:
        raise ContractError("PLAN_HASH_OR_SCHEMA")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1 or payload["core_version"] != VERSION or payload["repo"] != str(repo.resolve()):
        raise ContractError("PLAN_TARGET")
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(payload["created_at"])).total_seconds()
    except (TypeError, ValueError):
        raise ContractError("PLAN_AGE") from None
    if not 0 <= age <= 86400:
        raise ContractError("PLAN_AGE")
    expected = proposal(repo, payload["spec"])
    if payload["files"] != expected or payload["policy_before"] != compile_policy(repo)["policy_hash"] or payload["defaults_sha256"] != file_hash(Path(__file__).with_name("defaults.json")):
        raise ContractError("STALE_OR_TAMPERED_PLAN")
    journal = Path(journal).absolute()
    if journal.resolve().is_relative_to(repo.resolve()):
        raise ContractError("CONTROLLER_JOURNAL_OUTSIDE_REPO_REQUIRED")
    journal = external_directory(journal, repo)
    journal.mkdir(parents=True, exist_ok=False)
    paths = [safe_path(repo, item["relative"]) for item in expected]
    before = [path.read_bytes() if path.exists() else None for path in paths]
    if any((sha(data) if data is not None else None) != item["before_sha256"] for data, item in zip(before, expected)):
        raise ContractError("CONFIG_DRIFT")
    write_new(journal / "plan.json", payload)
    for index, data in enumerate(before):
        if data is not None:
            with (journal / f"before-{index}.bin").open("xb") as stream:
                stream.write(data)
    written = []
    try:
        for index, (path, item) in enumerate(zip(paths, expected)):
            path = safe_path(repo, item["relative"])
            path.parent.mkdir(parents=True, exist_ok=True)
            path = safe_path(repo, item["relative"])
            if file_hash(path) != item["before_sha256"]:
                raise ContractError("CONFIG_DRIFT")
            replace(path, encoded(item["value"]))
            written.append(index)
            if file_hash(safe_path(repo, item["relative"])) != item["after_sha256"]:
                raise ContractError("READBACK_HASH")
            write_new(journal / f"applied-{index}.json", {"relative": item["relative"], "sha256": item["after_sha256"]})
        effective = compile_policy(repo)
        result = {"status": "APPLIED", "plan_sha256": digest, "policy_hash": effective["policy_hash"],
                  "changed_files": [i["relative"] for i in expected], "provider_called": False,
                  "live_admission": "HELD", "multi_file_atomic": False}
        write_new(journal / "result.json", result)
        return result
    except BaseException:
        conflicts = []
        for index in reversed(written):
            try:
                path = safe_path(repo, expected[index]["relative"])
                if file_hash(path) != expected[index]["after_sha256"]:
                    conflicts.append(expected[index]["relative"])
                    continue
                if before[index] is None:
                    path.unlink()
                else:
                    replace(path, before[index])
            except (OSError, ContractError):
                conflicts.append(expected[index]["relative"])
        write_new(journal / "held.json", {"status": "HELD", "rollback_conflicts": conflicts,
                                          "multi_file_atomic": False})
        raise


def recover(repo, journal, expected_plan_sha256):
    """Manual recovery after interruption; never overwrite a later version."""
    repo = Path(repo).absolute()
    journal = external_directory(journal, repo)
    for relative in ("plan.json", "before-0.bin", "before-1.bin"):
        safe_path(journal, relative)
    payload, digest = load(journal / "plan.json", max_bytes=262144)
    if digest != expected_plan_sha256 or payload.get("repo") != str(repo.resolve()) or payload.get("core_version") != VERSION:
        raise ContractError("RECOVERY_PLAN")
    if [r.get("relative") for r in payload.get("files", [])] != list(TARGETS):
        raise ContractError("RECOVERY_TARGET")
    backups = {}
    for index, item in enumerate(payload["files"]):
        if sha(encoded(item["value"])) != item["after_sha256"]:
            raise ContractError("RECOVERY_HASH")
        if item["before_sha256"] is not None:
            with (journal / f"before-{index}.bin").open("rb") as stream:
                data = stream.read(65537)
            if len(data) > 65536 or sha(data) != item["before_sha256"]:
                raise ContractError("RECOVERY_BACKUP_HASH")
            backups[index] = data
    conflicts = []
    for index, item in reversed(list(enumerate(payload["files"]))):
        if sha(encoded(item["value"])) != item["after_sha256"]:
            raise ContractError("RECOVERY_HASH")
        path = safe_path(repo, item["relative"])
        current = file_hash(path)
        if current == item["before_sha256"]:
            continue
        if current != item["after_sha256"]:
            conflicts.append(item["relative"])
            continue
        if item["before_sha256"] is None:
            path.unlink()
        else:
            replace(path, backups[index])
    result = {"status": "HELD" if conflicts else "ROLLED_BACK", "conflicts": conflicts}
    write_new(journal / ("recovery-" + uuid.uuid4().hex + ".json"), result)
    return result
