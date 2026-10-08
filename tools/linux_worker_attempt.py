"""One explicitly authorized additional smoke; never retries or admits production.

Reuse the original runner's isolation, bounded execution and pure artifact gate.
The original intent is read-only. This separate fixed intent slot is exclusive,
including after crashes or unknown provider completion. Verification never dispatches.
"""
import argparse
import difflib
import json
import os
from pathlib import Path
import re
import shlex
import time
import uuid

from tools.linux_worker_smoke import (BWRAP_SHA, CLI_SHA, CODE_HOST_SHA, TEST_SHA,
    check_add_artifact, check_canaries, check_host_runtime, check_lifecycle,
    check_resource_limits, prepare, run_cgroup, sha, tree, write_new)

BASE_CHECKPOINT = '8d26fb9302dd5895bfa426927c4a60e6ba4fcc97'
OLD_INTENT_SHA = 'bc0e12a6964d52be021a38b1c3b01135e9100c1213e63f93f7f916bcf31fc6d9'
OLD_RESULT_SHA = 'c7236b38b03b497fb5197786c3c3734873f8eccb5087baead852db847dd18491'
OLD_EVENTS_SHA = '44bd312f38472d24d8b9a4d172b16d8dcf31839b37d28692c3010f275b6c4722'
CANARY_SHA = 'e051bd6f05707c1182a51317952e8fa729d3cd1eaaa268fcabd0f1d89c96c0e3'
EXTENDED_SHA = 'c78cfbe1cf97849563e2292fdc24e79d042e48cd3c8596379d87006efbe129ae'


def read_json(path):
    with path.open('rb') as source:
        raw = source.read(1048577)
    if len(raw) > 1048576:
        raise ValueError('EVIDENCE_SIZE_LIMIT')
    return json.loads(raw)


def identity(attempt_id, challenge):
    if str(uuid.UUID(attempt_id)) != attempt_id or not re.fullmatch('[0-9a-f]{64}', challenge):
        raise ValueError('CANONICAL_ATTEMPT_AND_CHALLENGE_REQUIRED')


def predecessor(root, admission):
    files = {root/'controller/smoke-intent.json': OLD_INTENT_SHA,
             admission/'smoke-result.json': OLD_RESULT_SHA,
             admission/'worker-events.jsonl': OLD_EVENTS_SHA}
    if any(path.is_symlink() or sha(path) != digest for path, digest in files.items()):
        raise ValueError('ORIGINAL_ATTEMPT_CHANGED')
    old = read_json(admission/'smoke-result.json')
    if old['status'] != 'FAILED_OR_UNKNOWN_NO_RETRY' or old['provider_launches'] != 1:
        raise ValueError('ORIGINAL_FAILED_ATTEMPT_REQUIRED')
    return {str(path): digest for path, digest in files.items()}


def canonical_commands(repo, challenge):
    return [shlex.join(['/usr/bin/python3', '-I', '-B', str(repo/'worker-boundary.py')])]


def worker_canary_source(root, attempt_id, challenge):
    identity(attempt_id, challenge)
    # Source is prepared by the controller before the snapshot, outside writable scope.
    return ('import contextlib, io, json, os, runpy\nfrom pathlib import Path\n'
            'r = Path('+repr(str(root))+')\nresults = {}\n'
            'for name, file in (("basic", "canary.py"), ("extended", "extended-canary.py")):\n'
            '    capture = io.StringIO()\n'
            '    with contextlib.redirect_stdout(capture):\n'
            '        runpy.run_path(str(r/"fixture-v2"/file), run_name="__main__")\n'
            '    results[name] = json.loads(capture.getvalue())\n'
            'keys = '+repr(sorted({'PATH','HOME','LANG','PWD','TMPDIR','CODEX_SANDBOX_NETWORK_DISABLED',
              'NO_COLOR','TERM','LC_CTYPE','LC_ALL','COLORTERM','PAGER','GIT_PAGER','GH_PAGER','CODEX_CI',
              'CODEX_THREAD_ID','CODEX_SESSION_ID','CODEX_VERSION','CODEX_PERMISSION_PROFILE',
              'CODEX_APPLY_PATCH_PRESERVE_LINE_ENDINGS','SHLVL','_'}))+'\n'
            'results["known_environment"] = {k: os.environ[k] for k in keys if k in os.environ}\n'
            'results["attempt_id"] = '+repr(attempt_id)+'\n'
            'results["challenge"] = '+repr(challenge)+'\n'
            'print(json.dumps(results, sort_keys=True))\n').encode()


def check_live_boundary(payload, root, thread_id, attempt_id, challenge):
    if payload.get('attempt_id') != attempt_id or payload.get('challenge') != challenge:
        raise ValueError('CHALLENGE_BINDING_FAILED')
    values = payload['known_environment']
    expected = {'PATH':'/usr/bin:/bin', 'HOME':str(root/'runtime-home'), 'LANG':'C.UTF-8',
                'PWD':str(root/'fixture-v2'), 'TMPDIR':str(root/'fixture-v2/.tmp'),
                'CODEX_SANDBOX_NETWORK_DISABLED':'1', 'NO_COLOR':'1', 'TERM':'dumb',
                'LC_CTYPE':'C.UTF-8', 'LC_ALL':'C.UTF-8', 'COLORTERM':'',
                'PAGER':'cat', 'GIT_PAGER':'cat', 'GH_PAGER':'cat', 'CODEX_CI':'1',
                'CODEX_THREAD_ID':thread_id, 'CODEX_VERSION':'0.161.0',
                'CODEX_PERMISSION_PROFILE':'worker-minimal', 'SHLVL':'0', '_':'/usr/bin/python3'}
    session_id = values.get('CODEX_SESSION_ID')
    if not isinstance(session_id, str) or str(uuid.UUID(session_id)) != session_id:
        raise ValueError('RUNTIME_SESSION_ID_INVALID')
    expected['CODEX_SESSION_ID'] = session_id  # Informational, not identity attestation.
    if 'CODEX_APPLY_PATCH_PRESERVE_LINE_ENDINGS' in values:
        expected['CODEX_APPLY_PATCH_PRESERVE_LINE_ENDINGS'] = '1'
    if values != expected or set(payload['extended']['environment_keys']) != set(expected):
        raise ValueError('LIVE_TOOL_ENVIRONMENT_DRIFT')
    if payload['extended'].get('real_user_home_canary') != {'access':'DENIED','errno':2}:
        raise ValueError('PUBLIC_HOME_CANARY_NOT_DENIED')
    status = dict(line.split(':', 1) for line in payload['basic']['status'])
    if (status.get('CapEff', '').strip() != '0000000000000000'
        or status.get('NoNewPrivs', '').strip() != '1' or status.get('Seccomp', '').strip() != '2'):
        raise ValueError('NATIVE_PROCESS_RESTRICTIONS_NOT_VERIFIED')
    # The two official entries have distinct runtime metadata; validate access unchanged.
    extended = {**payload['extended'], 'environment_keys':
                ['CODEX_SANDBOX_NETWORK_DISABLED','HOME','LANG','PATH','PWD','TMPDIR']}
    check_canaries({'real_canary': {'result': {'exitCode':0, 'stdout':json.dumps(payload['basic'])}},
                    'extended_canary': {'result': {'exitCode':0, 'stdout':json.dumps(extended)}}})


def command_matches(actual, expected):
    """Full literal argv, or one known shell wrapper containing that literal command."""
    if not isinstance(actual, str) or '\n' in actual or '\r' in actual:
        return False
    try:
        words = shlex.split(actual)
        return len(words) == 3 and words[0] == '/bin/bash' and words[1] == '-c' and words[2] == expected
    except ValueError:
        return False


def check_worker_events(raw, commands, root, attempt_id, challenge):
    """Parse each CLI frame once; never promote agent/output text to a runtime event."""
    if len(raw) > 262144:
        raise ValueError('EVENTS_SIZE_LIMIT')
    events = [json.loads(line) for line in raw.decode('utf-8').splitlines() if line]
    threads = [e for e in events if e.get('type') == 'thread.started']
    turns = [e for e in events if e.get('type') == 'turn.completed']
    if len(threads) != 1 or not threads[0].get('thread_id') or len(turns) != 1:
        raise ValueError('PROVIDER_COMPLETION_UNKNOWN_NO_RETRY')
    if any(e.get('type') in ('turn.failed', 'error') for e in events):
        raise ValueError('WORKER_TURN_FAILED_NO_RETRY')
    started, completed, accepted = {}, set(), {}
    for event in events:
        item = event.get('item', {})
        if item.get('type') != 'command_execution':
            continue
        identifier = item.get('id')
        if event.get('type') == 'item.started':
            if not identifier or identifier in started:
                raise ValueError('DUPLICATE_COMMAND_START')
            started[identifier] = item
        elif event.get('type') == 'item.completed':
            if identifier not in started or identifier in completed:
                raise ValueError('UNBOUND_OR_REPLAYED_COMMAND')
            completed.add(identifier)
            if started[identifier].get('command') != item.get('command'):
                raise ValueError('COMMAND_BINDING_CHANGED')
            if item.get('status') != 'completed' or item.get('exit_code') != 0:
                raise ValueError('WORKER_TOOL_FAILED_NO_RETRY')
            for index, expected in enumerate(commands):
                if command_matches(item.get('command'), expected):
                    if (index in accepted or item.get('status') != 'completed'
                        or item.get('exit_code') != 0 or not isinstance(item.get('aggregated_output'), str)):
                        raise ValueError('CANARY_COMMAND_FAILED_OR_REPLAYED')
                    accepted[index] = item
    if set(started) != completed:
        raise ValueError('WORKER_TOOL_COMPLETION_UNKNOWN_NO_RETRY')
    if set(accepted) != {0}:
        raise ValueError('REAL_CANARY_TOOL_EVIDENCE_MISSING')
    check_live_boundary(json.loads(accepted[0]['aggregated_output']), root, threads[0]['thread_id'], attempt_id, challenge)
    return {'thread_id': threads[0]['thread_id'], 'usage': turns[0].get('usage'),
            'command_item_ids': [accepted[0]['id']],
            'typed_command_execution': 'VERIFIED', 'code_mode_ancestry': 'NOT_DIRECTLY_OBSERVED'}


def current_admission(root, evidence, admission, cfg):
    effective = read_json(evidence/'effective-config-current.json')
    if effective.get('config_sha256') != sha(cfg) or effective.get('error'):
        raise ValueError('CURRENT_CONFIGURATION_REQUIRED')
    actual = effective['effective_config']
    for key, value in {'approval_policy': 'never', 'approvals_reviewer': 'auto_review',
                       'default_permissions': 'worker-minimal', 'model': 'gpt-6.1-sol',
                       'model_reasoning_effort': 'medium'}.items():
        if actual.get(key) != value:
            raise ValueError('CURRENT_POLICY_DRIFT')
    if actual.get('features', {}).get('code_mode_host') is not True:
        raise ValueError('CURRENT_HOST_NOT_ENABLED')
    check_canaries(effective)
    check_lifecycle(read_json(admission/'cgroup-lifecycle-code-host.json'), sha(cfg))
    check_host_runtime(admission, root, sha(cfg))


def verify(root, evidence, attempt_id, challenge, *, candidate=False):
    """Fresh controller process: recompute all custody/receipt bindings, never execute tools."""
    identity(attempt_id, challenge)
    intent_path = root/'controller/smoke-authorized-new-intent.json'
    intent = read_json(intent_path)
    result = read_json(evidence/('attempt-candidate.json' if candidate else 'attempt-result.json'))
    expected_status = 'CANDIDATE_NOT_ACCEPTED' if candidate else 'REAL_WORKER_SMOKE_PASS_REVIEW_HELD'
    if (intent['attempt_id'] != attempt_id or intent['challenge'] != challenge
        or intent['evidence_directory'] != str(evidence)
        or result.get('intent_sha256') != sha(intent_path)
        or result.get('attempt_id') != attempt_id or result.get('challenge') != challenge
        or result.get('status') != expected_status
        or result.get('production_admitted') is not False or result.get('review_passed') is not False):
        raise ValueError('ATTEMPT_BINDING_OR_ACCEPTANCE_REJECTED')
    repo = root/'fixture-v2'
    for path, digest in intent['prior_evidence'].items():
        if sha(Path(path)) != digest:
            raise ValueError('ORIGINAL_ATTEMPT_CHANGED')
    for path, digest in result['evidence_hashes'].items():
        if Path(path).name != path or sha(evidence/path) != digest:
            raise ValueError('DURABLE_EVIDENCE_TAMPERED')
    if not candidate and sha(evidence/'attempt-candidate.json') != result.get('candidate_sha256'):
        raise ValueError('ACCEPTANCE_CANDIDATE_CHANGED')
    if (sha(root/'runtime-home/config.toml') != intent['config_sha256']
        or sha(root/'bin/codex') != CLI_SHA or sha(root/'bin/codex-code-mode-host') != CODE_HOST_SHA
        or sha(root/'bin/codex-resources/bwrap') != BWRAP_SHA
        or sha(Path('/usr/bin/python3')) != intent['validator_executable_sha256']):
        raise ValueError('RUNTIME_PIN_DRIFT')
    after = tree(repo)
    changed = sorted(k for k in intent['before'].keys() | after.keys() if intent['before'].get(k) != after.get(k))
    if changed != ['artifact/mathutil.py'] or after != result['after']:
        raise ValueError('ARTIFACT_SCOPE_OR_SNAPSHOT_CHANGED')
    artifact = (repo/'artifact/mathutil.py').read_bytes()
    check_add_artifact(artifact)
    if sha(repo/'artifact/mathutil.py') != result['artifact_sha256'] or (evidence/'accepted-mathutil.py').read_bytes() != artifact:
        raise ValueError('ARTIFACT_CUSTODY_CHANGED')
    observed = check_worker_events((evidence/'worker-events.jsonl').read_bytes(), intent['canary_commands'], root, attempt_id, challenge)
    if observed != result['worker_observation']:
        raise ValueError('WORKER_OBSERVATION_CHANGED')
    for prefix in ('worker-events', 'validation'):
        execution = read_json(evidence/(prefix+'-execution.json'))
        if (execution['status'] != 'EXITED' or execution.get('exit_code') != 0
            or execution['output_limit_exceeded'] or not execution['output_readers_closed']
            or execution['remaining_cgroup_pids'] != []):
            raise ValueError('EXECUTION_RECEIPT_NOT_ACCEPTED')
        check_resource_limits(execution.get('kernel_resource_limits'))
        expected_unit = intent['unit'] if prefix == 'worker-events' else 'codex-smoke-validation-'+attempt_id+'.service'
        expected_group = '/user.slice/user-'+str(os.getuid())+'.slice/user@'+str(os.getuid())+'.service/app.slice/'+expected_unit
        if execution.get('unit') != expected_unit or execution.get('observed_control_group') != expected_group:
            raise ValueError('EXECUTION_CGROUP_BINDING_CHANGED')
    if (evidence/'validation.jsonl').read_bytes() != b'ACCEPTANCE_PASS\n':
        raise ValueError('VALIDATOR_OUTPUT_CHANGED')
    return {'status': 'READONLY_RESTART_VERIFIED', 'attempt_id': attempt_id,
            'artifact_sha256': result['artifact_sha256'], 'provider_launches': 0,
            'production_admitted': False, 'review_passed': False}


def finalize(root, evidence, report):
    """Publish one final receipt only after full candidate verification."""
    if report['status'] == 'CANDIDATE_NOT_ACCEPTED':
        write_new(evidence/'attempt-candidate.json', report)
        try:
            verify(root, evidence, report['attempt_id'], report['challenge'], candidate=True)
            report['candidate_sha256'] = sha(evidence/'attempt-candidate.json')
            report['status'] = 'REAL_WORKER_SMOKE_PASS_REVIEW_HELD'
        except Exception as exc:
            report['status'] = 'FAILED_OR_UNKNOWN_NO_RETRY'
            report['error'] = 'FINAL_VERIFICATION_FAILED:'+type(exc).__name__+':'+str(exc)
    write_new(evidence/'attempt-result.json', report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--admission-evidence', type=Path)
    parser.add_argument('--attempt-id', required=True)
    parser.add_argument('--challenge', required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    root, evidence = args.root, args.evidence
    identity(args.attempt_id, args.challenge)
    if args.verify:
        if args.execute: raise ValueError('VERIFY_NEVER_DISPATCHES')
        print(json.dumps(verify(root, evidence, args.attempt_id, args.challenge), indent=2))
        return 0
    admission = args.admission_evidence
    if admission is None: raise ValueError('PREVIOUS_ADMISSION_EVIDENCE_REQUIRED')
    repo, cli, cfg, env = prepare(root, evidence)
    old = predecessor(root, admission)
    current_admission(root, evidence, admission, cfg)
    if sha(repo/'canary.py') != CANARY_SHA or sha(repo/'extended-canary.py') != EXTENDED_SHA:
        raise ValueError('CANARY_SOURCE_PIN_DRIFT')
    intent_path = root/'controller/smoke-authorized-new-intent.json'
    if intent_path.exists(): raise ValueError('AUTHORIZED_ATTEMPT_ALREADY_CONSUMED_NO_RETRY')
    if not args.execute:
        print(json.dumps({'status': 'NEW_AUTHORIZED_ATTEMPT_READY', 'attempt_id': args.attempt_id,
                          'provider_launches': 0, 'production_admitted': False}, indent=2))
        return 0
    commands = canonical_commands(repo, args.challenge)
    prompt = ('Single authorized smoke '+args.attempt_id+'. First execute this exact command with '
              'tools.exec_command, shell="/bin/bash", login=false, tty=false, '
              'without prefixes, suffixes, pipes or echo substitutes:\n'+'\n'.join(commands)+
              '\nThen fix only artifact/mathutil.py so add(a,b) returns a+b. Run /usr/bin/python3 -B test_mathutil.py. '
              'Use the existing execution tools; do not create agents, commit, change other files or permissions. '
              'If a tool fails, stop and report it; do not retry. Report the change and actual test result.')
    worker = [str(cli), 'exec', '--strict-config', '--ignore-rules', '--json', '--ephemeral', '--color', 'never',
              '-C', str(repo), '-m', 'gpt-6.1-sol', '-c', 'model_reasoning_effort="medium"', prompt]
    unit = 'codex-authorized-smoke-'+args.attempt_id+'.service'
    before = tree(repo)
    if (repo/'worker-boundary.py').read_bytes() != worker_canary_source(root, args.attempt_id, args.challenge):
        raise ValueError('PINNED_WORKER_BOUNDARY_SOURCE_REQUIRED')
    intent = {'attempt_id': args.attempt_id, 'challenge': args.challenge, 'base_checkpoint': BASE_CHECKPOINT,
              'authorization_source': 'EXPLICIT_USER_SINGLE_NEW_SMOKE_2026_10_08',
              'scope': 'REAL_WORKER_ARTIFACT_VALIDATION_ONLY', 'retry_budget': 0,
              'evidence_directory': str(evidence), 'prior_evidence': old, 'before': before,
              'allowed_files': ['artifact/mathutil.py'], 'canary_commands': commands, 'worker_argv': worker,
              'unit': unit, 'config_sha256': sha(cfg), 'binary_sha256': CLI_SHA, 'host_sha256': CODE_HOST_SHA,
              'validator_executable_sha256': sha(Path('/usr/bin/python3')), 'created_unix': time.time()}
    write_new(intent_path, intent)
    report = {'attempt_id': args.attempt_id, 'challenge': args.challenge, 'intent_sha256': sha(intent_path),
              'status': 'DISPATCH_INTENT_DURABLE', 'provider_launches': 1,
              'production_admitted': False, 'review_passed': False,
              'configured_model': 'gpt-6.1-sol', 'configured_effort': 'medium',
              'provider_attested_model': None, 'provider_attested_effort': None}
    write_new(evidence/'attempt-started.json', report)
    try:
        execution = run_cgroup(worker, unit, 120, repo, env, evidence, 'worker-events')
        report['execution'] = execution
        if execution['status'] != 'EXITED' or execution.get('exit_code') != 0 or execution['output_limit_exceeded']:
            raise ValueError('WORKER_FAILED_OR_UNKNOWN_NO_RETRY')
        report['worker_observation'] = check_worker_events((evidence/'worker-events.jsonl').read_bytes(), commands, root, args.attempt_id, args.challenge)
        after = tree(repo)
        changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
        report['changed_paths'] = changed
        if changed != ['artifact/mathutil.py']: raise ValueError('ARTIFACT_SCOPE_REJECTED')
        data = (repo/'artifact/mathutil.py').read_bytes()
        check_add_artifact(data)
        validator = [str(cli), 'sandbox', '-P', 'worker-minimal', '-C', str(repo),
                     '-c', 'permissions.worker-minimal.filesystem.:workspace_roots.artifact="read"',
                     '/usr/bin/python3', '-B', str(repo/'test_mathutil.py')]
        if sha(repo/'test_mathutil.py') != TEST_SHA: raise ValueError('VALIDATOR_PIN_DRIFT')
        validation = run_cgroup(validator, 'codex-smoke-validation-'+args.attempt_id+'.service',
                                15, repo, env, evidence, 'validation')
        if (validation['status'] != 'EXITED' or validation.get('exit_code') != 0 or validation['output_limit_exceeded']
            or tree(repo) != after or (repo/'artifact/mathutil.py').read_bytes() != data
            or (evidence/'validation.jsonl').read_bytes() != b'ACCEPTANCE_PASS\n'):
            raise ValueError('VALIDATION_FAILED_OR_UNKNOWN_NO_RETRY')
        write_new(evidence/'artifact-manifest.json', {'attempt_id': args.attempt_id, 'challenge': args.challenge,
                  'files': {'artifact/mathutil.py': sha(repo/'artifact/mathutil.py')}, 'after': after})
        with (evidence/'accepted-mathutil.py').open('xb') as out:
            out.write(data); out.flush(); os.fsync(out.fileno())
        with (evidence/'artifact.diff').open('x') as out:
            out.write(''.join(difflib.unified_diff(['def add(a, b):\n', '    return a - b\n'],
                       data.decode().splitlines(keepends=True), fromfile='before/artifact/mathutil.py', tofile='after/artifact/mathutil.py')))
        report.update({'status': 'CANDIDATE_NOT_ACCEPTED', 'after': after,
                       'artifact_sha256': sha(repo/'artifact/mathutil.py')})
        report['evidence_hashes'] = {name: sha(evidence/name) for name in ('worker-events.jsonl', 'worker-events.log',
            'worker-events-execution.json', 'validation.jsonl', 'validation.log', 'validation-execution.json',
            'artifact-manifest.json', 'artifact.diff', 'accepted-mathutil.py', 'effective-config-current.json')}
        predecessor(root, admission)
        if (sha(cfg) != intent['config_sha256'] or sha(cli) != CLI_SHA
            or sha(root/'bin/codex-code-mode-host') != CODE_HOST_SHA
            or sha(root/'bin/codex-resources/bwrap') != BWRAP_SHA
            or sha(Path('/usr/bin/python3')) != intent['validator_executable_sha256']):
            raise ValueError('RUNTIME_PIN_DRIFT')
    except Exception as exc:
        report['status'] = 'FAILED_OR_UNKNOWN_NO_RETRY'
        report['error'] = type(exc).__name__+':'+str(exc)
    finalize(root, evidence, report)
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'REAL_WORKER_SMOKE_PASS_REVIEW_HELD' else 1


if __name__ == '__main__':
    raise SystemExit(main())
