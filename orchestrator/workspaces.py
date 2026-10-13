"""Controller-owned Git allocation and immutable data validation oracle."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

from .contracts import fingerprint, relative_file, ContractError


def git(repo, *args):
    repo = Path(repo).resolve(strict=True)
    root = repo.parent if repo.name in {"fixture-repo", "source-repo"} else repo.parents[1] if repo.parent.name == "worktrees" else None
    if root is None:
        raise ContractError("GIT_OUTSIDE_SYNTHETIC_FIXTURE")
    if repo.name == 'source-repo':
        from .policy import load
        record, _ = load(root / 'controller/repo-adapter.json', max_bytes=2 * 1024 * 1024)
        if record.get('repo') != str(repo) or record.get('mode') != 'DEVELOPMENT_REPO':
            raise ContractError('REPO_ADAPTER_GIT_BINDING')
    hooks, template = root / "controller-git-hooks", root / "controller-git-template"
    for directory in (hooks, template):
        if (not directory.is_dir() or directory.is_symlink() or directory.is_junction()
                or any(directory.iterdir())):
            raise ContractError("GIT_EMPTY_CONTROLS_CHANGED")
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("GIT_")}
    run = subprocess.run(["git", "-c", "core.hooksPath=" + str(hooks),
                          "-c", "init.templateDir=" + str(template),
                          "-c", "commit.gpgSign=false", "-c", "tag.gpgSign=false",
                          "-C", str(repo), *args], env=env, capture_output=True, timeout=30,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if run.returncode:
        # Raw Git stderr could contain unrelated paths/config; keep local fixed category.
        raise ContractError("GIT_OPERATION_FAILED:" + args[0])
    return run.stdout.decode("utf-8", errors="strict").strip()


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")


def fixture_repo(root):
    root = Path(root).resolve(strict=True)
    (root / "controller-git-hooks").mkdir()
    (root / "controller-git-template").mkdir()
    repo = root / "fixture-repo"
    repo.mkdir()
    (repo / "AGENTS.md").write_text(
        "# Synthetic worker fixture\n\n"
        "Follow Global Shared Agent Core. Only write the task's explicitly assigned result JSON.\n"
        "Do not spawn agents/processes or access networks, credentials, other worktrees, or controller state.\n"
        "Do not change Git metadata, instructions or tests. Return a short completion report.\n", encoding="utf-8")
    git(repo, "init", "-b", "fixture-baseline")
    git(repo, "add", "--", "AGENTS.md")
    git(repo, "-c", "user.name=Local Fixture", "-c", "user.email=fixture@localhost.invalid",
        "commit", "-m", "test: synthetic worker baseline")
    return repo, git(repo, "rev-parse", "HEAD")


def allocate(root, repo, claim):
    root = Path(root).resolve(strict=True)
    path = root / "worktrees" / claim["attempt_id"]
    path.parent.mkdir(exist_ok=True)
    git(repo, "worktree", "add", "--detach", str(path), claim["task"]["base_sha"])
    temp = root / "worker-temp" / claim["attempt_id"]
    temp.mkdir(parents=True)
    return path, temp


def scan(path, *, ignore_scratch=False, max_bytes=2 * 1024 * 1024, max_files=256):
    path = Path(path).resolve(strict=True)
    result = {}
    total = 0
    count = 0
    for child in path.rglob("*"):
        rel = child.relative_to(path).as_posix()
        if child.is_symlink() or child.is_junction():
            raise ContractError("REPARSE_ARTIFACT")
        if rel == ".git" and not child.is_file():
            raise ContractError("GIT_LINK_CHANGED")
        if child.is_dir():
            continue
        if not child.is_file():
            raise ContractError("NONREGULAR_ARTIFACT")
        size = child.stat().st_size
        count += 1
        total += size
        if total > max_bytes or count > max_files:
            raise ContractError("ARTIFACT_SIZE_LIMIT")
        if ignore_scratch and rel.startswith('.tmp/'):
            # Fixed native scratch only. Reparse/special/size checks still run;
            # this is not an arbitrary caller-supplied exclusion list.
            continue
        with child.open('rb') as stream:
            result[rel] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return result


def validate_artifact(worktree, claim, baseline):
    """Controller oracle parses data only: never executes worker-generated code."""
    task = claim["task"]
    after = scan(worktree)
    changed = sorted(k for k in set(baseline) | set(after) if baseline.get(k) != after.get(k))
    if git(worktree, "rev-parse", "HEAD") != task["base_sha"]:
        raise ContractError("WORKER_CHANGED_HEAD")
    if not changed or any(name not in task["allowed_files"] for name in changed):
        raise ContractError("OUT_OF_SCOPE_DIFF")
    file = Path(worktree) / relative_file(task["allowed_files"][0])
    if file.stat().st_size > 4096:
        raise ContractError("RESULT_SIZE_LIMIT")
    value = json.loads(file.read_text(encoding="utf-8"))
    numbers = task["inputs"]["numbers"]
    if (type(value) is not dict or set(value) != {"sum", "count"}
            or type(value["sum"]) is not int or type(value["count"]) is not int
            or value["sum"] != sum(numbers) or value["count"] != len(numbers)):
        raise ContractError("ORACLE_MISMATCH")
    return {"status": "PASS", "task_hash": claim["task_hash"], "attempt_id": claim["attempt_id"],
            "lease_epoch": claim["epoch"], "base_sha": task["base_sha"],
            "head_sha": git(worktree, "rev-parse", "HEAD"), "changed_files": changed,
            "artifact_sha256": after[task["allowed_files"][0]],
            "oracle_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "oracle": "fixture_sum_v1", "scope_gate": "PASS",
            "sandbox_write_boundary": "NOT_VERIFIED_BY_DIFF_GATE"}
