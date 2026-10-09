"""Controller-owned, bounded same-turn recovery; never an execution permission."""
import json
import re
import shlex
import threading
import time
from pathlib import Path

from .contracts import ContractError, canonical, fingerprint
from .evidence import digest, frozen_bytes, guarded

LEGACY_POLICY = {'version': 1, 'max_recoverable_failures': 3, 'recovery_seconds': 60,
          'new_dispatch_retries': 0, 'unknown': 'STOP'}
POLICY = {**LEGACY_POLICY, 'version': 2}


def literal_argv(command):
    """One native literal command, optionally wrapped by the official shell."""
    try:
        argv = shlex.split(command)
        if len(argv) == 3 and argv[0] in {'/bin/bash', '/bin/sh', '/usr/bin/bash'} and argv[1] in {'-lc', '-c'}:
            argv = shlex.split(argv[2])
        return tuple(argv)
    except (ValueError, TypeError):
        return ()
DENIAL = re.compile(r'permission denied|operation not permitted|read.only file system|'
                    r'(?:sandbox|approval|authorization)[^\n]{0,80}(?:denied|failed|violation)|'
                    r'lease (?:lost|expired)|stale (?:lease|result)|fenc(?:ed|ing)|'
                    r'timed? out|timeout|cancelled|canceled', re.I)
ORDINARY = re.compile(r'command not found|(?:Assertion|Syntax|Indentation|ModuleNotFound|Name|Type|Reference)Error|'
                      r'(?:^|\n)FAILED \(|={2,} FAILURES ={2,}|\b\d+ failed\b|\berror (?:TS|CS)\d+', re.I)


def classify(event):
    """Only pinned CLI envelopes are input. Tool stdout supplies no authority."""
    if type(event) is not dict or not isinstance(event.get('type'), str):
        return 'PROTOCOL_UNKNOWN', 'STOP'
    kind = event['type']
    if kind in {'error', 'turn.failed'}:
        return 'PROVIDER_UNKNOWN', 'STOP'
    if kind not in {'thread.started', 'turn.started', 'turn.completed',
                    'item.started', 'item.updated', 'item.completed'}:
        return 'PROTOCOL_UNKNOWN', 'STOP'
    if not kind.startswith('item.'):
        return None
    item = event.get('item')
    if type(item) is not dict or not isinstance(item.get('type'), str):
        return 'PROTOCOL_UNKNOWN', 'STOP'
    tool = item['type']
    if tool not in {'command_execution', 'file_change', 'agent_message', 'reasoning', 'todo_list'}:
        return 'UNEXPECTED_TOOL', 'STOP'
    if tool not in {'command_execution', 'file_change'}:
        return None
    # Negative signals have priority, even when a command claims exit 0.
    text = item.get('aggregated_output', '')
    if not isinstance(text, str):
        return 'PROTOCOL_UNKNOWN', 'STOP'
    if DENIAL.search(text) or item.get('error'):
        return 'PROTECTION_OR_CONTROL_FAILURE', 'STOP'
    if kind != 'item.completed':
        return None
    status, code = item.get('status'), item.get('exit_code')
    if status == 'completed' and (tool == 'file_change' or type(code) is int and code == 0):
        return None
    if (tool == 'command_execution' and status == 'failed' and type(code) is int
            and code in {1, 2, 127} and ORDINARY.search(text)):
        return 'ORDINARY_TOOL_OR_TEST_FAILURE', 'RECOVER'
    return 'TOOL_FAILURE_UNKNOWN', 'STOP'


class WorkerFailureMonitor:
    def __init__(self, folder, binding, runtime_seconds, on_stop, *, policy=None, checks=(), clock=time.monotonic):
        self.folder, self.binding = guarded(folder), dict(binding)
        self.policy = dict(POLICY if policy is None else policy)
        if (set(self.policy) != set(POLICY) or type(self.policy['version']) is not int or self.policy['version'] not in {1, 2}
                or type(self.policy['max_recoverable_failures']) is not int
                or not 0 <= self.policy['max_recoverable_failures'] <= POLICY['max_recoverable_failures']
                or type(self.policy['recovery_seconds']) not in (int, float)
                or not 0 < self.policy['recovery_seconds'] <= POLICY['recovery_seconds']
                or type(self.policy['new_dispatch_retries']) is not int
                or self.policy['new_dispatch_retries'] != 0 or self.policy['unknown'] != 'STOP'
                or type(runtime_seconds) not in (int, float) or not 0 < runtime_seconds <= 600):
            raise ContractError('WORKER_FAILURE_POLICY')
        self.lock, self.clock, self.on_stop = threading.RLock(), clock, on_stop
        self.start = clock()
        self.deadline, self.recovery_deadline = self.start + runtime_seconds, None
        self.repair_remaining = self.policy['recovery_seconds']
        self.unresolved, self.active_check = set(), None
        self.suite_success = set()
        self.checks = {}
        for check in checks:
            argv, seconds = tuple(check['argv']), check['timeout_seconds']
            if (not argv or any(not isinstance(a, str) or not a for a in argv)
                    or type(seconds) not in (int, float) or not 0 < seconds <= 600 or argv in self.checks):
                raise ContractError('WORKER_CHECK_BUDGET')
            self.checks[argv] = seconds
        self.buffer, self.total, self.count, self.sequence = b'', 0, 0, 0
        self.completed, self.stopped, self.reason = False, False, None
        self.control_unknown = False
        self.seen = set()
        self.config = {'binding': self.binding, 'policy': self.policy,
                       'runtime_seconds': runtime_seconds, 'started_unix': time.time()}
        if self.policy['version'] == 2:
            self.config['checks'] = [{'argv': list(a), 'timeout_seconds': s} for a, s in self.checks.items()]
        self.last_hash = fingerprint(self.config)
        # Exclusive creation rejects parser/attempt replay; recovery is audit-only.
        frozen_bytes(self.folder / 'policy.json', canonical(self.config).encode())

    def _record(self, category, action, raw=b''):
        self.sequence += 1
        value = {'sequence': self.sequence, 'binding_hash': fingerprint(self.binding),
                 'failure_policy_hash': fingerprint(self.policy), 'previous_hash': self.last_hash,
                 'observed_unix': time.time(), 'elapsed_seconds': self.clock() - self.start,
                 'category': category, 'action': action, 'recoverable_failures': self.count,
                 'recovery_deadline_elapsed': None if self.recovery_deadline is None else self.recovery_deadline - self.start,
                 'raw_event_sha256': digest(raw) if raw else None}
        if self.policy['version'] == 2:
            value.update(repair_seconds_remaining=self.repair_remaining,
                         unresolved_commands_hash=fingerprint(sorted(self.unresolved)),
                         active_check=self.active_check)
        frozen_bytes(self.folder / ('%06d.json' % self.sequence), canonical(value).encode())
        self.last_hash = fingerprint(value)

    def stop(self, reason, raw=b''):
        with self.lock:
            if self.stopped:
                return
            self.stopped, self.reason = True, reason  # Latch before any disk/DB callback.
            try:
                self._record(reason, 'STOP', raw)
            except Exception:
                self.control_unknown = True
                raise
            finally:
                try:
                    self.on_stop(reason)  # Must cancel even if evidence persistence fails.
                except Exception:
                    self.control_unknown = True
                    raise

    def tick(self):
        with self.lock:
            if self.stopped or self.completed and self.policy['version'] == 1:
                return
            now = self.clock()
            if now >= self.deadline:
                self.stop('TASK_TIMEOUT')
            elif self.active_check and now >= self.active_check['deadline']:
                self.stop('REQUIRED_CHECK_TIMEOUT')
            elif not self.completed and not self.active_check and self.recovery_deadline is not None and now >= self.recovery_deadline:
                self.stop('RECOVERY_TIME_EXHAUSTED')

    def _check_lifecycle(self, event, raw):
        """Only pinned command lifecycle can pause repair accounting, never prose."""
        if self.policy['version'] != 2 or not event['type'].startswith('item.'):
            return
        item = event['item']
        if event['type'] == 'item.completed' and item['type'] == 'file_change':
            self.suite_success.clear()
        if item['type'] != 'command_execution':
            return
        argv = literal_argv(item.get('command'))
        if event['type'] == 'item.started' and argv in self.checks:
            if self.active_check or not isinstance(item.get('id'), str) or not item['id']:
                self.stop('CHECK_LIFECYCLE_UNKNOWN', raw)
                return
            now = self.clock()
            self.active_check = {'id': item['id'], 'argv': list(argv), 'started': now,
                                 'deadline': min(self.deadline, now + self.checks[argv])}
            self._record('PINNED_CHECK_STARTED', 'OBSERVE', raw)
        if event['type'] == 'item.completed':
            if argv in self.checks and not self.active_check:
                self.stop('CHECK_LIFECYCLE_UNKNOWN', raw)
                return
            if self.active_check:
                check = self.active_check
                if check['id'] != item.get('id') or tuple(check['argv']) != argv:
                    self.stop('CHECK_LIFECYCLE_UNKNOWN', raw)
                    return
                if self.recovery_deadline is not None:
                    self.recovery_deadline += self.clock() - check['started']
                self.active_check = None
                self._record('PINNED_CHECK_ENDED', 'OBSERVE', raw)
            success = item.get('status') == 'completed' and type(item.get('exit_code')) is int and item['exit_code'] == 0
            if success and argv in self.checks:
                self.suite_success.add(argv)
            else:
                self.suite_success.clear()
            category = 'EXACT_COMMAND_RECOVERED'
            if success and argv in self.unresolved:
                self.unresolved.remove(argv)
            if self.checks and self.suite_success == set(self.checks):
                # Full pinned acceptance after the last failure/edit/non-check
                # also closes missing-tool/argument repairs using legal fallbacks.
                self.unresolved.clear()
                category = 'PINNED_ACCEPTANCE_SUITE_RECOVERED'
            if success and not self.unresolved and self.recovery_deadline is not None:
                self.repair_remaining = max(0, self.recovery_deadline - self.clock())
                self.recovery_deadline = None
                self._record(category, 'RESOLVED', raw)

    def feed(self, data):
        with self.lock:
            if self.stopped:
                return
            self.tick()
            if self.stopped:
                return
            self.total += len(data)
            self.buffer += data
            if self.total > 262144:
                self.stop('OUTPUT_LIMIT')
                return
            while b'\n' in self.buffer and not self.stopped:
                # A disk callback in this same chunk may have consumed the deadline.
                self.tick()
                if self.stopped:
                    break
                raw, self.buffer = self.buffer.split(b'\n', 1)
                if len(raw) > 65536:
                    self.stop('EVENT_LINE_LIMIT')
                    break
                if not raw:
                    continue
                try:
                    def pairs(items):
                        value = {}
                        for key, item in items:
                            if key in value:
                                raise ValueError('duplicate')
                            value[key] = item
                        return value
                    event = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite')))
                except (ValueError, UnicodeError):
                    self.stop('PROTOCOL_UNKNOWN', raw)
                    break
                if self.completed:
                    self.stop('EVENT_AFTER_COMPLETION', raw)
                    break
                decision = classify(event)
                if decision and decision[1] == 'STOP':
                    self.stop(decision[0], raw)
                    break
                if event['type'] == 'item.completed':
                    key = event['item'].get('id')
                    if not isinstance(key, str) or not key or key in self.seen:
                        self.stop('EVENT_REPLAY_OR_UNKNOWN', raw)
                        break
                    self.seen.add(key)
                try:
                    self._check_lifecycle(event, raw)
                except Exception:
                    self.control_unknown = True
                    self.stop('EVIDENCE_UNKNOWN', raw)
                    raise
                if self.stopped:
                    break
                if decision:
                    self.count += 1
                    if self.policy['version'] == 2:
                        argv = literal_argv(event['item'].get('command'))
                        if not argv:
                            self.stop('RECOVERY_COMMAND_UNKNOWN', raw)
                            break
                        self.unresolved.add(argv)
                    if self.recovery_deadline is None:
                        self.recovery_deadline = min(self.deadline, self.clock() + self.repair_remaining)
                    if self.count > self.policy['max_recoverable_failures']:
                        self.stop('RECOVERY_COUNT_EXHAUSTED', raw)
                        break
                    try:
                        self._record(decision[0], 'RECOVER', raw)
                    except Exception:
                        self.control_unknown = True
                        self.stop('EVIDENCE_UNKNOWN', raw)
                        raise
                if event['type'] == 'turn.completed':
                    self.tick()
                    if self.active_check:
                        self.stop('CHECK_LIFECYCLE_UNKNOWN', raw)
                    if self.policy['version'] == 2 and self.unresolved and not self.stopped:
                        self.stop('UNRESOLVED_TOOL_FAILURE', raw)
                    if not self.stopped:
                        self.completed = True
            if len(self.buffer) > 65536 and not self.stopped:
                self.stop('EVENT_LINE_LIMIT')

    def finish(self):
        with self.lock:
            self.tick()
            if self.buffer or not self.completed:
                self.stop('PROVIDER_UNKNOWN')
            return self.summary()

    def summary(self):
        with self.lock:
            return {'failure_policy_hash': fingerprint(self.policy), 'policy': self.policy,
                    'recoverable_failures': self.count, 'stopped': self.stopped, 'reason': self.reason,
                    'control_unknown': self.control_unknown,
                    'completion_observed': self.completed, 'last_record_hash': self.last_hash,
                    'unresolved_commands': [list(a) for a in sorted(self.unresolved)],
                    'task_seconds_remaining': max(0, self.deadline - self.clock())}


def audit_failure_log(folder, binding):
    """Read-only recovery: never recreate a monitor or replenish execution budget."""
    folder = guarded(folder)
    config = json.loads((folder / 'policy.json').read_bytes())
    if config['binding'] != binding:
        raise ContractError('FAILURE_EVIDENCE_BINDING')
    previous, rows = fingerprint(config), []
    for index, path in enumerate(sorted(folder.glob('[0-9]*.json')), 1):
        value = json.loads(path.read_bytes())
        if (path.name != '%06d.json' % index or value['sequence'] != index
                or value['binding_hash'] != fingerprint(binding)
                or value['failure_policy_hash'] != fingerprint(config['policy'])
                or value['previous_hash'] != previous):
            raise ContractError('FAILURE_EVIDENCE_DRIFT')
        previous = fingerprint(value)
        rows.append(value)
    return {'records': rows, 'last_record_hash': previous, 'execution_resumed': False}
