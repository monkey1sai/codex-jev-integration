"""One authorized synthetic CLI smoke, separate from production queue admission.

Requires the prepared, isolated Linux fixture and verified native canaries.
Never installs, logs in, imports reviews, retries a model, or changes policy.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import threading
import time
import tomllib
import uuid

CLI_SHA = '9a820c17865fa825d04db416818679a9d63bd72e50835c396f496e5684626c9c'
BWRAP_SHA = '77360cb751ccedc5971391444ac86a8a33c15b04d6b4a6fe45f5d25496e62c4c'
CODE_HOST_SHA = 'e87096087c02aa6ab90a5a85031659665aa0bf3ee20c07ca0b8ab701c83fcd5b'
TEST_SHA = '2fe4181a4fc52bd647e904f01e45bb102d3f466cd6931c5d7b33cba40670c5be'
DISABLED = ('multi_agent', 'multi_agent_v2', 'apps', 'plugins', 'hooks',
            'computer_use', 'browser_use', 'browser_use_external', 'in_app_browser',
            'daemon_auto_start', 'request_permissions_tool',
            'exec_permission_approvals', 'skill_mcp_dependency_install', 'skill_search',
            'workspace_dependencies', 'unbounded_connection_retries', 'remote_plugin',
            'auth_elicitation', 'tool_suggest')


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def write_new(path, data):
    with path.open('x', encoding='utf-8') as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())


def tree(repo):
    """Do not follow task-controlled symlinks or include private scratch output."""
    result = {}
    count = total = 0
    for folder, dirs, files in os.walk(repo, followlinks=False):
        base = Path(folder)
        if base == repo:
            dirs[:] = [d for d in dirs if d != '.tmp']
        for name in [*dirs, *files]:
            path = base / name
            relative = path.relative_to(repo).as_posix()
            info = path.lstat()
            count += 1
            if count > 256:
                raise ValueError('TREE_COUNT_LIMIT')
            if stat.S_ISLNK(info.st_mode):
                if relative != 'controller-link':
                    raise ValueError('TASK_SYMLINK_REJECTED')
                result[relative] = {'symlink': os.readlink(path)}
            elif stat.S_ISREG(info.st_mode):
                total += info.st_size
                if info.st_nlink != 1 or info.st_size > 1048576 or total > 8388608:
                    raise ValueError('TREE_FILE_LIMIT')
                result[relative] = sha(path)
            elif not stat.S_ISDIR(info.st_mode):
                raise ValueError('SPECIAL_FILE_REJECTED')
    return result


def check_canaries(effective):
    for name in ('real_canary', 'extended_canary'):
        if effective[name].get('result', {}).get('exitCode') != 0:
            raise ValueError('NATIVE_CANARY_FAILED')
    basic = json.loads(effective['real_canary']['result']['stdout'])
    extended = json.loads(effective['extended_canary']['result']['stdout'])
    for key in ('workspace_read', 'workspace_write', 'git_read'):
        if basic[key].get('access') != 'ALLOWED':
            raise ValueError('POSITIVE_CANARY_FAILED:'+key)
    for key in ('controller_read', 'controller_write', 'credential_home_read',
                'credential_home_write', 'other_worktree_read', 'other_worktree_write',
                'proc_host_root', 'windows_controller_read'):
        if basic[key] != {'access': 'DENIED', 'errno': 2, 'reason': 'No such file or directory'}:
            raise ValueError('FILESYSTEM_CANARY_FAILED:'+key)
    for key in ('network', 'docker_socket', 'dbus_socket'):
        if basic[key].get('access') != 'DENIED' or basic[key].get('errno') != 1:
            raise ValueError('NETWORK_ENFORCEMENT_NOT_PROVEN:'+key)
    if basic['git_write'].get('access') != 'DENIED' or basic['git_write'].get('errno') != 30:
        raise ValueError('GIT_WRITE_NOT_BLOCKED')
    if basic['mount_c_visible'] or basic['windows_interop_visible']:
        raise ValueError('WSL_HOST_CHANNEL_VISIBLE')
    for key, number in {'bin_write': 30, 'bwrap_write': 30, 'controller_symlink_read': 2,
                        'controller_symlink_write': 2, 'env_file_read': 13,
                        'env_file_write': 30, 'wsl_init_read': 2}.items():
        if extended[key] != {'access': 'DENIED', 'errno': number}:
            raise ValueError('EXTENDED_CANARY_FAILED:'+key)
    if extended['run_wsl_entries'] != [] or extended['binfmt_entries'] != []:
        raise ValueError('WSL_INTEROP_NOT_EMPTY')
    allowed_env = {'CODEX_SANDBOX_NETWORK_DISABLED', 'HOME', 'LANG', 'PATH', 'PWD', 'TMPDIR'}
    if set(extended['environment_keys']) != allowed_env:
        raise ValueError('TOOL_ENVIRONMENT_DRIFT')


def check_lifecycle(lifecycle, config_sha):
    cases = lifecycle.get('cases', [])
    if lifecycle.get('config_sha256') != config_sha or len(cases) != 3:
        raise ValueError('CURRENT_LIFECYCLE_EVIDENCE_REQUIRED')
    if sorted(c.get('case', '') for c in cases) != ['cancel', 'controller_interruption', 'timeout']:
        raise ValueError('LIFECYCLE_CASES_REQUIRED')
    if any(c.get('status') != 'PASS' or c.get('remaining_after_final_cleanup') != [] for c in cases):
        raise ValueError('LIFECYCLE_ADMISSION_FAILED')


def check_resource_limits(values):
    if values != {'memory.max': '1073741824', 'memory.swap.max': '0', 'pids.max': '64'}:
        raise ValueError('KERNEL_RESOURCE_LIMITS_UNVERIFIED')


def check_host_runtime(evidence, root, config_sha):
    lifecycle = json.loads((evidence/'host-lifecycle-result.json').read_text())
    check_lifecycle(lifecycle, config_sha)
    for case in lifecycle['cases']:
        if case.get('host_executable') != str(root/'bin/codex-code-mode-host'):
            raise ValueError('ACTUAL_HOST_EXECUTABLE_REQUIRED')
        check_resource_limits(case.get('kernel_resource_limits'))
    execution = json.loads((evidence/'host-protocol-execution.json').read_text())
    if (execution.get('status') != 'EXITED' or execution.get('exit_code') != 0
        or execution.get('output_limit_exceeded') or execution.get('remaining_cgroup_pids') != []):
        raise ValueError('ACTUAL_HOST_PROTOCOL_EXECUTION_REQUIRED')
    check_resource_limits(execution.get('kernel_resource_limits'))
    data = json.loads((evidence/'host-protocol.jsonl').read_text())
    responses = data.get('results', [])
    if len(responses) != 5:
        raise ValueError('HOST_PROTOCOL_CASES_REQUIRED')
    values = [v['result']['value']['Result'] for v in responses]
    texts = [[c.get('text') for c in v['content_items']] for v in values]
    expected_globals = {name: 'undefined' for name in ('process', 'require', 'fetch', 'Deno', 'Bun')}
    if (json.loads(texts[0][0]) != expected_globals or texts[1] != ['IMPORT_REJECTED']
        or texts[2] != [] or values[2]['error_text'] != 'Unsupported import in exec: node:fs'
        or texts[3] != ['UNKNOWN_TOOL_REJECTED'] or texts[4] != ['5']
        or any(values[n]['error_text'] is not None for n in (0, 1, 3, 4))):
        raise ValueError('HOST_API_RESTRICTIONS_NOT_VERIFIED')


def check_add_artifact(data):
    """This tiny synthetic contract permits no import-time executable code."""
    if len(data) > 65536:
        raise ValueError('ARTIFACT_SIZE_LIMIT')
    module = ast.parse(data.decode('utf-8'))
    body = list(module.body)
    def strip_docstring(items):
        if items and isinstance(items[0], ast.Expr) and isinstance(items[0].value, ast.Constant) and isinstance(items[0].value.value, str):
            return items[1:]
        return items
    body = strip_docstring(body)
    if len(body) != 1 or not isinstance(body[0], ast.FunctionDef):
        raise ValueError('PURE_ADD_FUNCTION_REQUIRED')
    fn = body[0]
    args = fn.args
    if (fn.name != 'add' or fn.decorator_list or fn.returns or fn.type_params
        or args.posonlyargs or args.vararg or args.kwarg or args.kwonlyargs or args.defaults
        or [a.arg for a in args.args] != ['a', 'b'] or any(a.annotation for a in args.args)):
        raise ValueError('PURE_ADD_SIGNATURE_REQUIRED')
    instructions = strip_docstring(fn.body)
    if len(instructions) != 1 or not isinstance(instructions[0], ast.Return):
        raise ValueError('PURE_ADD_RETURN_REQUIRED')
    value = instructions[0].value
    if not (isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add)
            and isinstance(value.left, ast.Name) and value.left.id == 'a'
            and isinstance(value.right, ast.Name) and value.right.id == 'b'):
        raise ValueError('PURE_ADD_EXPRESSION_REQUIRED')


def run_cgroup(command, unit, seconds, repo, env, evidence, prefix):
    """Own descendants independently of launcher lifetime; cap each output stream."""
    control_env = {**env, 'XDG_RUNTIME_DIR': '/run/user/'+str(os.getuid())}
    argv = ['/usr/bin/systemd-run', '--user', '--unit='+unit, '--pipe', '--wait', '--collect',
            '--property=KillMode=control-group', '--property=TimeoutStopSec=2s',
            '--property=RuntimeMaxSec='+str(seconds)+'s', '--property=SendSIGKILL=yes',
            '--property=MemoryMax=1073741824', '--property=MemorySwapMax=0',
            '--property=TasksMax=64',
            '/usr/bin/env', '-i', *[k+'='+v for k, v in env.items()], *command]
    record = {'argv': argv, 'unit': unit, 'status': 'STARTING'}
    exceeded = threading.Event()
    handles = []
    process = None
    def pump(stream, path):
        total = 0
        try:
            with path.open('xb') as out:
                while data := stream.read(4096):
                    total += len(data)
                    if total > 262144:
                        exceeded.set()
                        break
                    out.write(data)
        except Exception:
            exceeded.set()
    try:
        process = subprocess.Popen(argv, cwd=repo, env=control_env,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        record['controller_pid'] = process.pid
        write_new(evidence/(prefix+'-started.json'), record)
        for stream, suffix in ((process.stdout, '.jsonl'), (process.stderr, '.log')):
            handle = threading.Thread(target=pump, args=(stream, evidence/(prefix+suffix)), daemon=True)
            handle.start(); handles.append(handle)
        deadline = time.monotonic()+seconds+5
        record['unit_details'] = ''
        while process.poll() is None and not exceeded.is_set() and time.monotonic() < deadline:
            if not record['unit_details']:
                details = subprocess.run(['/usr/bin/systemctl', '--user', 'show', unit,
                                          '--property=MainPID,ControlGroup,KillMode,RuntimeMaxUSec,MemoryMax,MemorySwapMax,TasksMax'],
                                         env=control_env, capture_output=True, text=True, timeout=5)
                if details.returncode == 0 and 'MainPID=0\n' not in details.stdout:
                    record['unit_details'] = details.stdout
                    fields = dict(line.split('=', 1) for line in details.stdout.splitlines() if '=' in line)
                    expected = '/user.slice/user-'+str(os.getuid())+'.slice/user@'+str(os.getuid())+'.service/app.slice/'+unit
                    if fields.get('ControlGroup') == expected:
                        folder = Path('/sys/fs/cgroup'+expected)
                        record['kernel_resource_limits'] = {name: (folder/name).read_text().strip()
                                                           for name in ('memory.max', 'memory.swap.max', 'pids.max')}
            time.sleep(.05)
        record['output_limit_exceeded'] = exceeded.is_set()
        if process.poll() is None:
            record['status'] = 'OUTPUT_LIMIT' if exceeded.is_set() else 'TIMEOUT_OR_UNKNOWN'
        else:
            record['exit_code'] = process.returncode
            record['status'] = 'EXITED'
    except Exception as exc:
        record['error'] = type(exc).__name__+':'+str(exc)
        record['status'] = 'EXECUTION_UNKNOWN'
    finally:
        try:
            stop = subprocess.run(['/usr/bin/systemctl', '--user', 'stop', unit], env=control_env,
                                  capture_output=True, timeout=10)
            record['stop_exit'] = stop.returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            record['stop_exit'] = None
            record['stop_error'] = type(exc).__name__
            record['status'] = 'CLEANUP_UNVERIFIED'
        if process is not None and process.poll() is None:
            process.kill(); process.wait(timeout=5)
        for handle in handles: handle.join(timeout=5)
        record['output_limit_exceeded'] = exceeded.is_set()
        record['output_readers_closed'] = all(not h.is_alive() for h in handles)
        expected = '/user.slice/user-'+str(os.getuid())+'.slice/user@'+str(os.getuid())+'.service/app.slice/'+unit
        details = dict(line.split('=', 1) for line in record.get('unit_details', '').splitlines() if '=' in line)
        observed = details.get('ControlGroup')
        record['observed_control_group'] = observed
        remaining = []
        if observed != expected:
            record['status'] = 'CLEANUP_UNVERIFIED'
        if any(details.get(key) != value for key, value in
               {'MemoryMax': '1073741824', 'MemorySwapMax': '0', 'TasksMax': '64'}.items()):
            record['status'] = 'RESOURCE_LIMITS_UNVERIFIED'
        try:
            check_resource_limits(record.get('kernel_resource_limits'))
        except ValueError:
            record['status'] = 'RESOURCE_LIMITS_UNVERIFIED'
        cgroup = Path('/sys/fs/cgroup'+expected)
        if observed == expected and cgroup.exists():
            for path in cgroup.rglob('cgroup.procs'):
                remaining.extend(path.read_text().split())
        record['remaining_cgroup_pids'] = remaining
        if remaining or not record['output_readers_closed']:
            record['status'] = 'CLEANUP_UNVERIFIED'
        write_new(evidence/(prefix+'-execution.json'), record)
    return record


def prepare(root, evidence):
    if sys.platform != 'linux' or os.getuid() == 0:
        raise ValueError('NON_ROOT_LINUX_REQUIRED')
    for path in (root, evidence):
        if not path.is_absolute() or path.resolve() != path:
            raise ValueError('EXISTING_LITERAL_NON_SYMLINK_PATH_REQUIRED')
        if not path.is_dir() or path.stat().st_uid != os.getuid():
            raise ValueError('OWNED_EXISTING_DIRECTORY_REQUIRED')
    repo = root / 'fixture-v2'
    cli = root / 'bin/codex'
    cfg = root / 'runtime-home/config.toml'
    if sha(cli) != CLI_SHA or sha(root/'bin/codex-resources/bwrap') != BWRAP_SHA:
        raise ValueError('OFFICIAL_BINARY_PIN_MISMATCH')
    # Custom install-context "Other" resolves this helper beside the CLI.
    host = root/'bin/codex-code-mode-host'
    if host.is_symlink() or sha(host) != CODE_HOST_SHA:
        raise ValueError('OFFICIAL_CODE_MODE_HOST_PIN_MISMATCH')
    conf = tomllib.loads(cfg.read_text())
    expected_keys = {'default_permissions', 'approval_policy', 'approvals_reviewer',
                     'model', 'model_reasoning_effort', 'web_search', 'analytics',
                     'features', 'shell_environment_policy', 'permissions', 'skills'}
    if set(conf) != expected_keys:
        raise ValueError('UNEXPECTED_CONFIGURATION_OR_PROVIDER')
    for key, value in {'approval_policy': 'never', 'approvals_reviewer': 'auto_review',
                       'default_permissions': 'worker-minimal', 'model': 'gpt-6.1-sol',
                       'model_reasoning_effort': 'medium', 'web_search': 'disabled'}.items():
        if conf[key] != value:
            raise ValueError('CONFIGURATION_FLOOR_MISMATCH:'+key)
    if conf['features'] != {**{k: False for k in DISABLED},
                            'skip_host_skill_discovery': True, 'code_mode_host': True}:
        raise ValueError('UNEXPECTED_FEATURE_OR_EXTERNAL_TOOL')
    permissions = {'worker-minimal': {'filesystem': {
        ':minimal': 'read', 'glob_scan_max_depth': 3, str(root/'bin'): 'read',
        ':workspace_roots': {'.': 'read', 'artifact': 'write', '.tmp': 'write',
                             '.git': 'read', '.codex': 'read', '.agents': 'read',
                             '**/*.env': 'deny'}}, 'network': {'enabled': False}}}
    if conf['permissions'] != permissions:
        raise ValueError('PERMISSIONS_FLOOR_MISMATCH')
    env = {'PATH': '/usr/bin:/bin', 'HOME': str(root/'runtime-home'),
           'CODEX_HOME': str(root/'runtime-home'), 'LANG': 'C.UTF-8',
           'TMPDIR': str(repo/'.tmp')}
    if conf['shell_environment_policy'] != {'inherit': 'none', 'set': {k: env[k] for k in ('PATH', 'LANG', 'HOME', 'TMPDIR')}}:
        raise ValueError('ENVIRONMENT_FLOOR_MISMATCH')
    if conf['analytics'] != {'enabled': False}:
        raise ValueError('UNEXPECTED_ANALYTICS')
    skills = root/'runtime-home/skills'
    system = skills/'.system'
    builtin = {'openai-docs', 'skill-installer', 'skill-creator', 'imagegen', 'review-agent'}
    if skills.is_symlink() or system.is_symlink() or {p.name for p in skills.iterdir()} != {'.system'}:
        raise ValueError('EXTERNAL_SKILL_REJECTED')
    if {p.name for p in system.iterdir()} != builtin | {'.codex-system-skills.marker'}:
        raise ValueError('UNEXPECTED_BUILTIN_SKILL')
    disabled_skills = sorted((str(system/n/'SKILL.md'), False) for n in builtin)
    if sorted((v['path'], v['enabled']) for v in conf['skills']['config']) != disabled_skills:
        raise ValueError('BUILTIN_SKILLS_NOT_DISABLED')
    if any(p.exists() for p in (repo/'.codex', root/'runtime-home/rules',
                               root/'runtime-home/plugins',
                               Path('/etc/codex/config.toml'), Path('/etc/codex/requirements.toml'))):
        raise ValueError('UNREVIEWED_LAYER_OR_RULES')
    if not repo.is_dir() or sha(repo/'test_mathutil.py') != TEST_SHA:
        raise ValueError('FIXTURE_ACCEPTANCE_PIN_MISMATCH')
    if (repo/'artifact/mathutil.py').read_bytes() != b'def add(a, b):\n    return a - b\n':
        raise ValueError('FRESH_SYNTHETIC_BASELINE_REQUIRED')
    for name in ('artifact', '.tmp', '.git'):
        if (repo/name).is_symlink():
            raise ValueError('SYMLINK_SCOPE_REJECTED')
    for public in (root/'controller/sentinel', root/'other-worktree/sentinel',
                   root/'runtime-home/fake-secret-canary', repo/'fake.env'):
        if not public.is_file() or public.is_symlink():
            raise ValueError('HOST_CANARY_TARGET_MISSING')
    return repo, cli, cfg, env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--execute', action='store_true', help='Consume the authorized one-worker budget; no automatic retry')
    args = parser.parse_args()
    root, evidence = args.root, args.evidence
    repo, cli, cfg, env = prepare(root, evidence)
    report = {'scope': 'SINGLE_SYNTHETIC_WORKER_SMOKE_ONLY', 'production_admitted': False,
              'review_passed': False, 'configured_model': 'gpt-6.1-sol', 'configured_effort': 'medium',
              'provider_attested_model': None, 'provider_attested_effort': None,
              'binary_sha256': sha(cli), 'code_host_sha256': CODE_HOST_SHA,
              'config_sha256': sha(cfg), 'provider_launches': 0}
    # The official CLI handles auth; never read/copy/print credential stores.
    auth = subprocess.run([str(cli), 'login', 'status'], env=env, cwd=repo,
                          capture_output=True, timeout=10)
    report['login_status_exit'] = auth.returncode
    if auth.returncode != 0:
        report['status'] = 'BLOCKED_AUTHENTICATION'
        write_new(evidence/('smoke-auth-'+uuid.uuid4().hex+'.json'), report)
        print(json.dumps(report, indent=2))
        return 2
    # These are controller-owned diagnostic receipts, never provider attestations.
    lifecycle = json.loads((evidence/'cgroup-lifecycle-code-host.json').read_text())
    check_lifecycle(lifecycle, sha(cfg))
    effective = json.loads((evidence/'effective-config-code-host.json').read_text())
    if effective.get('config_sha256') != sha(cfg) or effective.get('error'):
        raise ValueError('CURRENT_EFFECTIVE_CONFIGURATION_REQUIRED')
    actual = effective['effective_config']
    for key in ('approval_policy', 'approvals_reviewer', 'model', 'model_reasoning_effort', 'default_permissions'):
        if actual.get(key) != tomllib.loads(cfg.read_text())[key]:
            raise ValueError('EFFECTIVE_CONFIGURATION_MISMATCH')
    check_canaries(effective)
    if actual.get('features', {}).get('code_mode_host') is not True:
        raise ValueError('EFFECTIVE_CODE_MODE_HOST_REQUIRED')
    check_host_runtime(evidence, root, sha(cfg))
    report['code_host_protocol'] = 'VERIFIED_HOST_ONLY'
    report['model_tool_dispatch'] = 'NOT_YET_VERIFIED'
    if (root/'controller/smoke-intent.json').exists():
        report['status'] = 'PREPARED_REEXECUTION_REQUIRES_NEW_AUTHORIZATION'
        print(json.dumps(report, indent=2))
        return 2
    if not args.execute:
        report['status'] = 'READY_NO_MODEL_LAUNCHED'
        print(json.dumps(report, indent=2))
        return 0
    before = tree(repo)
    task = {'goal': 'Correct add(a, b) to return their sum.', 'allowed_files': ['artifact/mathutil.py'],
            'acceptance': 'python3 -B test_mathutil.py', 'retry_budget': 0}
    unit = 'codex-orchestrator-smoke-'+uuid.uuid4().hex+'.service'
    worker = [str(cli), 'exec', '--strict-config', '--ignore-rules', '--json', '--ephemeral',
              '--color', 'never', '-C', str(repo), '-m', 'gpt-6.1-sol',
              '-c', 'model_reasoning_effort="medium"',
              'Fix only artifact/mathutil.py: add(a,b) must return a+b. Run python3 -B test_mathutil.py. '
              'Do not change other files or create agents. Report the change and test result.']
    # A fixed root-scoped exclusive intent prevents replays, even with another evidence folder.
    intent = {'task': task, 'before': before, 'worker_argv': worker, 'unit': unit,
              'config_sha256': sha(cfg), 'binary_sha256': sha(cli), 'created_unix': time.time()}
    write_new(root/'controller/smoke-intent.json', intent)
    report['intent_sha256'] = sha(root/'controller/smoke-intent.json')
    report['unit'] = unit
    report['worker_argv'] = worker
    report['provider_launches'] = 1
    write_new(evidence/'smoke-started.json', report)
    execution = run_cgroup(worker, unit, 120, repo, env, evidence, 'worker-events')
    report['execution'] = execution
    after = tree(repo)
    report['changed_paths'] = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    if execution['status'] != 'EXITED' or execution.get('exit_code') != 0 or execution['output_limit_exceeded'] or report['changed_paths'] != ['artifact/mathutil.py']:
        report['status'] = 'FAILED_OR_UNKNOWN_NO_RETRY'
    elif (sha(cfg) != report['config_sha256'] or sha(cli) != CLI_SHA
          or sha(root/'bin/codex-code-mode-host') != CODE_HOST_SHA
          or sha(root/'bin/codex-resources/bwrap') != BWRAP_SHA):
        report['status'] = 'FAILED_PIN_DRIFT_NO_RETRY'
    else:
        artifact = repo/'artifact/mathutil.py'
        if artifact.is_symlink() or artifact.stat().st_size > 65536:
            raise ValueError('ARTIFACT_CUSTODY_REJECTED')
        data = artifact.read_bytes()
        check_add_artifact(data)
        validation_command = [str(cli), 'sandbox', '-P', 'worker-minimal', '-C', str(repo),
                              '-c', 'permissions.worker-minimal.filesystem.:workspace_roots.artifact="read"',
                              '/usr/bin/python3', '-B', str(repo/'test_mathutil.py')]
        validation = run_cgroup(validation_command, 'codex-orchestrator-validation-'+uuid.uuid4().hex+'.service',
                                15, repo, env, evidence, 'validation')
        report['validation'] = validation
        valid = (validation['status'] == 'EXITED' and validation.get('exit_code') == 0
                 and not validation['output_limit_exceeded'] and tree(repo) == after
                 and artifact.read_bytes() == data
                 and (evidence/'validation.jsonl').read_bytes() == b'ACCEPTANCE_PASS\n')
        report['status'] = 'WORKER_SMOKE_VERIFIED_REVIEW_HELD' if valid else 'FAILED_VALIDATION_NO_RETRY'
        if valid:
            with (evidence/'accepted-mathutil.py').open('xb') as out: out.write(data)
            report['artifact_sha256'] = hashlib.sha256(data).hexdigest()
    report['events_sha256'] = sha(evidence/'worker-events.jsonl')
    write_new(evidence/'smoke-result.json', report)
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'WORKER_SMOKE_VERIFIED_REVIEW_HELD' else 1


if __name__ == '__main__':
    raise SystemExit(main())
