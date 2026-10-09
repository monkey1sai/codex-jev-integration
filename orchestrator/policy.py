"""Custom controller precedence. This does not alter native Codex settings."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re

from .contracts import ContractError, fingerprint, relative_file

VERSION = "1.0.0"
MAX_BYTES = 65536
FLOORS = {"live_execution": False, "external_writes": False, "native_children": 0,
          "required_review": True, "independent_review": True,
          "review_model": "gpt-6-astra", "review_min_effort": "high",
          "hooks": False, "merge_execution": False}
MODELS = {"gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna", "gpt-6-astra"}
EFFORTS = {"low", "medium", "high", "xhigh", "max", "ultra"}
FIELDS = {"schema_version", "roles", "scheduler", "routing", "capabilities", "validators", "guidance"}


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", value):
        raise ContractError("IDENTIFIER")
    return value


def resource_units(value):
    if type(value) is not dict or len(value) > 16:
        raise ContractError('RESOURCE_CONFIG')
    for name, units in value.items():
        identifier(name)
        if type(units) is not int or not 1 <= units <= 65536:
            raise ContractError('RESOURCE_CONFIG')
    return value


def safe_path(root, relative):
    """Reject all symlinks/junctions, including ancestors of the explicit root."""
    root = Path(root).absolute()
    if not root.is_dir():
        raise ContractError("WORKSPACE_REQUIRED")
    target = root / relative
    for node in [target, *target.parents]:
        if node.is_symlink() or node.is_junction():
            raise ContractError("REPARSE_PATH")
    if not target.resolve().is_relative_to(root.resolve()):
        raise ContractError("PATH_ESCAPES_ROOT")
    return target


def load(path, max_bytes=MAX_BYTES):
    with Path(path).open("rb") as stream:
        data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ContractError("CONFIG_TOO_LARGE")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ContractError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result
    try:
        value = json.loads(data.decode("utf-8-sig"), object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ContractError("NONFINITE_JSON")))
    except (UnicodeError, ValueError) as error:
        if isinstance(error, ContractError):
            raise
        raise ContractError("INVALID_JSON") from None
    return value, hashlib.sha256(data).hexdigest()


def validate_overlay(value):
    if type(value) is not dict or set(value) - FIELDS:
        raise ContractError("UNKNOWN_POLICY_FIELD")
    if "schema_version" in value and (type(value["schema_version"]) is not int or value["schema_version"] != 1):
        raise ContractError("POLICY_SCHEMA")
    for section in ("roles", "scheduler", "routing", "capabilities", "validators"):
        if section in value and type(value[section]) is not dict:
            raise ContractError("POLICY_SHAPE")
    for role, settings in value.get("roles", {}).items():
        if role not in {"planner", "worker", "researcher", "reviewer"} or type(settings) is not dict or set(settings) != {"model", "reasoning_effort"}:
            raise ContractError("ROLE_CONFIG")
        if not isinstance(settings["model"], str) or not isinstance(settings["reasoning_effort"], str) or settings["model"] not in MODELS or settings["reasoning_effort"] not in EFFORTS:
            raise ContractError("MODEL_CONFIG")
        if role == "reviewer" and (settings["model"] != "gpt-6-astra" or settings["reasoning_effort"] not in {"high", "xhigh", "max", "ultra"}):
            raise ContractError("REVIEW_FLOOR")
    caps = {"max_active": 2, "max_queued": 1000, "max_dispatches": 1000, "max_attempts": 2}
    for key, number in value.get("scheduler", {}).items():
        if key == 'resource_limits':
            resource_units(number)
            continue
        if key not in caps or type(number) is not int or not 1 <= number <= caps[key]:
            raise ContractError("SCHEDULER_LIMIT")
    for key, option in value.get("routing", {}).items():
        if key == "strategy" and isinstance(option, str) and option in {"rules_only", "rules_then_jev"}:
            continue
        if key == "jev_enabled" and type(option) is bool:
            continue
        raise ContractError("ROUTING_CONFIG")
    for name, cap in value.get("capabilities", {}).items():
        identifier(name)
        if type(cap) is not dict or set(cap) - {'resources'} != {"role", "description", "allowed_files", "validators"}:
            raise ContractError("CAPABILITY_CONFIG")
        resource_units(cap.get('resources', {}))
        if not isinstance(cap["role"], str) or cap["role"] not in {"worker", "researcher", "reviewer"} or not isinstance(cap["description"], str) or not 1 <= len(cap["description"]) <= 2000:
            raise ContractError("CAPABILITY_CONFIG")
        for field in ("allowed_files", "validators"):
            if type(cap[field]) is not list or len(cap[field]) > 64 or any(not isinstance(s, str) for s in cap[field]) or len(set(s.casefold() for s in cap[field])) != len(cap[field]):
                raise ContractError("CAPABILITY_CONFIG")
        for name in cap["allowed_files"]:
            relative_file(name)
        for name in cap["validators"]:
            identifier(name)
    for name, validator in value.get("validators", {}).items():
        identifier(name)
        if type(validator) is not dict or set(validator) != {"argv", "timeout_seconds"}:
            raise ContractError("VALIDATOR_CONFIG")
        if type(validator["argv"]) is not list or not 1 <= len(validator["argv"]) <= 32 or any(not isinstance(s, str) or not s or len(s) > 2000 or "\x00" in s for s in validator["argv"]):
            raise ContractError("VALIDATOR_CONFIG")
        if type(validator["timeout_seconds"]) is not int or not 1 <= validator["timeout_seconds"] <= 600:
            raise ContractError("VALIDATOR_CONFIG")
    if "guidance" in value:
        if type(value["guidance"]) is not list or len(value["guidance"]) > 32:
            raise ContractError("GUIDANCE_CONFIG")
        for name in value["guidance"]:
            relative_file(name)
    return value


def merge(base, overlay):
    validate_overlay(base)
    validate_overlay(overlay)
    result = deepcopy(base)
    for key, value in overlay.items():
        if key in {"roles", "scheduler", "routing", "capabilities", "validators"}:
            result.setdefault(key, {}).update(deepcopy(value))
        else:
            result[key] = deepcopy(value)
    validate_overlay(result)
    return result


def compile_policy(repo, *, defaults=None, session=None, execution_mode='high_assurance'):
    if execution_mode not in {'high_assurance', 'development'}:
        raise ContractError('EXECUTION_MODE')
    repo = Path(repo).absolute()
    safe_path(repo, ".codex/orchestrator.json")
    source = Path(defaults) if defaults else Path(__file__).with_name("defaults.json")
    base, digest = load(source)
    if set(base) != FIELDS:
        raise ContractError("DEFAULTS_SCHEMA")
    validate_overlay(base)
    sources = [{"layer": "global_defaults", "path": str(source.resolve()), "sha256": digest}]
    def leaves(value, prefix=''):
        for key, item in value.items():
            name = prefix + key
            if type(item) is dict and item:
                yield from leaves(item, name + '.')
            else:
                yield name
    provenance = {key: 0 for key in leaves(base)}
    override = safe_path(repo, ".codex/orchestrator.json")
    local = {}
    if override.exists():
        local, digest = load(override)
        base = merge(base, local)
        sources.append({"layer": "repo", "path": str(override), "sha256": digest})
        provenance.update({key: len(sources) - 1 for key in leaves(local)})
    if session is not None:
        validate_overlay(session)
        # An explicit repo ceiling cannot be silently raised by a session.
        for key, ceiling in local.get('scheduler', {}).items():
            option = session.get('scheduler', {}).get(key)
            if option is None:
                continue
            if key == 'resource_limits':
                if any(option.get(name, limit) > limit for name, limit in ceiling.items()):
                    raise ContractError('REPO_SCHEDULER_CEILING')
            elif option > ceiling:
                raise ContractError('REPO_SCHEDULER_CEILING')
        # A session may specialize work but cannot weaken explicit repo acceptance.
        for name, cap in session.get('capabilities', {}).items():
            old = base['capabilities'].get(name)
            if old and (not set(old['validators']) <= set(cap['validators'])
                        or not set(cap['allowed_files']) <= set(old['allowed_files'])
                        or cap['role'] != old['role']
                        or any(cap.get('resources', {}).get(r, 0) < units
                               for r, units in old.get('resources', {}).items())):
                raise ContractError('REPO_ACCEPTANCE_DOWNGRADE')
        for name, validator in session.get('validators', {}).items():
            if name in base['validators'] and validator != base['validators'][name]:
                raise ContractError('REPO_VALIDATOR_OVERRIDE')
        effort_rank = {'low': 0, 'medium': 1, 'high': 2, 'xhigh': 3, 'max': 4, 'ultra': 5}
        review = session.get('roles', {}).get('reviewer')
        if review and effort_rank.get(review.get('reasoning_effort'), -1) < effort_rank[base['roles']['reviewer']['reasoning_effort']]:
            raise ContractError('REVIEW_FLOOR')
        base = merge(base, session)
        sources.append({"layer": "explicit_session", "sha256": fingerprint(session)})
        provenance.update({key: len(sources) - 1 for key in leaves(session)})
    for cap in base["capabilities"].values():
        if set(cap["validators"]) - set(base["validators"]):
            raise ContractError("UNKNOWN_VALIDATOR")
        for name, units in cap.get('resources', {}).items():
            if units > base['scheduler'].get('resource_limits', {}).get(name, 0):
                raise ContractError('RESOURCE_REQUIREMENT')
    # Jev has its own existing precedence, kept separate from controller policy.
    jev_path = safe_path(repo, ".codex/jev.json")
    if jev_path.exists():
        jev, digest = load(jev_path)
        validate_jev(jev)
        if jev.get("enabled") is False:
            base["routing"]["jev_enabled"] = False
        sources.append({"layer": "repo_jev", "path": str(jev_path), "sha256": digest})
        if jev.get('enabled') is False:
            provenance['routing.jev_enabled'] = len(sources) - 1
    code_names = ("__init__.py", "contracts.py", "store.py", "policy.py", "tasks.py", "core_queue.py", "routing.py", "provision.py", "__main__.py", "phase2.py", "pipeline.py", "processes.py", "workspaces.py", "cli_adapter.py", "mock_v2_worker.py", "evidence.py", "snapshots.py", "validators.py", "supervisor.py", "merge_validation.py", "admission.py", "development.py", "worker_failures.py")
    code_hashes = {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in code_names}
    for name in ('orchestrator/repo_adapter.py', 'tools/game_repo_campaign.py', 'tools/repo_parallel_campaign.py', 'tools/game_repo_acceptance.mjs', 'tools/development_validator.py', 'tools/development_smoke.py', 'tools/linux_worker_smoke.py'):
        code_hashes[name] = hashlib.sha256((Path(__file__).resolve().parents[1] / name).read_bytes()).hexdigest()
    floors = deepcopy(FLOORS)
    floors['live_execution'] = execution_mode == 'development'
    return {"core_version": VERSION, "repo_identity": str(repo.resolve()).casefold(),
            "execution_mode": execution_mode,
            "settings": base, "floors": floors, "sources": sources,
            "field_sources": {key: sources[provenance[key]] for key in leaves(base)},
            "floor_source": {'layer': 'compiled', 'version': VERSION},
            "core_sha256": code_hashes,
            "policy_hash": fingerprint({"version": VERSION, "mode": execution_mode, "settings": base, "floors": floors, "sources": sources, "core": code_hashes}),
            "native_effective_config": "UNVERIFIED", "live_admission": "NATIVE_TRUST_REQUIRES_EXECUTION" if execution_mode == 'development' else "HELD"}


def validate_jev(value):
    if type(value) is not dict or set(value) - {"enabled", "confidence_threshold", "timeout_seconds", "observability"}:
        raise ContractError("JEV_CONFIG")
    if "enabled" in value and type(value["enabled"]) is not bool:
        raise ContractError("JEV_CONFIG")
    for key, low, high in (("confidence_threshold", 0, 1), ("timeout_seconds", 1, 20)):
        if key in value and (type(value[key]) not in (int, float) or not math.isfinite(value[key]) or not low <= value[key] <= high):
            raise ContractError("JEV_CONFIG")
    if "observability" in value:
        obs = value["observability"]
        if type(obs) is not dict or set(obs) - {"enabled", "max_records", "max_bytes"}:
            raise ContractError("JEV_CONFIG")
        if "enabled" in obs and type(obs["enabled"]) is not bool:
            raise ContractError("JEV_CONFIG")
        for key, low, high in (("max_records", 1, 1000), ("max_bytes", 1024, 2097152)):
            if key in obs and (type(obs[key]) is not int or not low <= obs[key] <= high):
                raise ContractError("JEV_CONFIG")
    return value
