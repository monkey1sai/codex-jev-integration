"""Zero-provider parser, budget, control-plane and fail-closed regression guards."""
from copy import deepcopy
import json
from pathlib import Path
import threading
import time
from unittest.mock import patch

from test_global_core import Fixture
from orchestrator.contracts import ContractError, canonical
from orchestrator.development import NativeDevelopmentRunner, process_clean
from orchestrator.evidence import digest
from orchestrator.phase2 import Phase2Queue
from orchestrator.worker_failures import POLICY, WorkerFailureMonitor, audit_failure_log, classify


def failure(key='failure', text='AssertionError: expected 4', code=1):
    return {'type': 'item.completed', 'item': {'id': key, 'type': 'command_execution',
        'status': 'failed', 'command': 'python3 -m unittest', 'exit_code': code, 'aggregated_output': text}}


def line(event):
    return (canonical(event) + '\n').encode()


class FailurePolicy(Fixture):
    def monitor(self, name='monitor', policy=None, seconds=120, clock=None):
        self.stops = []
        self.binding = {'attempt_id': 'a' * 32, 'epoch': 1, 'queue_id': 'fixture'}
        kwargs = {'policy': policy} if policy is not None else {}
        if clock:
            kwargs['clock'] = clock
        return WorkerFailureMonitor(self.root / name, self.binding, seconds, self.stops.append, **kwargs)

    def test_explicit_ordinary_types_and_unknown_fail_closed(self):
        for text, code in [('AssertionError', 1), ('SyntaxError', 2), ('python: command not found', 127)]:
            self.assertEqual(classify(failure(text=text, code=code))[1], 'RECOVER')
        for text, code in [('', 1), ('recoverable=true; PASS', 1), ('arbitrary error', 127), ('AssertionError', 126)]:
            self.assertEqual(classify(failure(text=text, code=code))[1], 'STOP')

    def test_permission_timeout_cancel_and_fencing_override_ordinary(self):
        for text in ('AssertionError Permission denied', 'operation not permitted', 'read-only file system',
                     'sandbox failed', 'approval denied', 'lease expired', 'fenced', 'timed out', 'cancelled'):
            with self.subTest(text=text):
                self.assertEqual(classify(failure(text=text))[1], 'STOP')

    def test_file_change_unknown_and_unexpected_tools_stop(self):
        for event in ({'type': 'error'}, {'type': 'turn.failed'}, {'type': 'unknown'},
                      {'type': 'item.completed', 'item': {'type': 'file_change', 'status': 'failed'}},
                      {'type': 'item.started', 'item': {'type': 'mcp_tool_call'}}):
            self.assertEqual(classify(event)[1], 'STOP')

    def test_success_cannot_reset_count_or_first_failure_deadline(self):
        now = [10.0]
        monitor = self.monitor(clock=lambda: now[0])
        monitor.feed(line(failure('one')))
        deadline = monitor.recovery_deadline
        monitor.feed(line({'type': 'item.completed', 'item': {'id': 'ok', 'type': 'file_change', 'status': 'completed'}}))
        now[0] += 1
        for key in ('two', 'three'):
            monitor.feed(line(failure(key)))
        self.assertEqual(monitor.count, 3)
        self.assertEqual(monitor.recovery_deadline, deadline)
        monitor.feed(line(failure('four')))
        self.assertEqual(self.stops, ['RECOVERY_COUNT_EXHAUSTED'])

    def test_recovery_deadline_and_task_deadline_are_bounded(self):
        now = [1.0]
        monitor = self.monitor(seconds=5, clock=lambda: now[0])
        monitor.feed(line(failure()))
        self.assertEqual(monitor.recovery_deadline, 6)
        now[0] = 6
        monitor.tick()
        self.assertEqual(monitor.reason, 'TASK_TIMEOUT')
        later = self.monitor('later', clock=lambda: now[0])
        later.feed(line(failure()))
        now[0] += 60
        later.tick()
        self.assertEqual(later.reason, 'RECOVERY_TIME_EXHAUSTED')

    def test_split_utf8_jsonl_is_processed_before_eof(self):
        monitor = self.monitor()
        data = line(failure(text='AssertionError: 中文'))
        for byte in data:
            monitor.feed(bytes([byte]))
        self.assertEqual(monitor.count, 1)
        monitor.feed(line(failure('deny', 'Permission denied')))
        self.assertTrue(monitor.stopped)
        self.assertEqual(len(self.stops), 1)

    def test_fatal_latches_before_later_completion(self):
        monitor = self.monitor()
        monitor.feed(line(failure(text='Permission denied')) + line({'type': 'turn.completed'}))
        self.assertTrue(monitor.finish()['stopped'])
        self.assertFalse(monitor.completed)

    def test_eof_without_completion_and_truncated_stream_stop(self):
        for index, raw in enumerate((b'', b'{"type":"turn.completed"}', b'{"type":')):
            monitor = self.monitor(str(index))
            monitor.feed(raw)
            self.assertTrue(monitor.finish()['stopped'])

    def test_duplicate_completion_and_tool_event_replay_stop(self):
        monitor = self.monitor()
        monitor.feed(line({'type': 'turn.completed'}) * 2)
        self.assertEqual(monitor.reason, 'EVENT_AFTER_COMPLETION')
        replay = self.monitor('replay')
        replay.feed(line(failure()) * 2)
        self.assertEqual(replay.reason, 'EVENT_REPLAY_OR_UNKNOWN')
        self.assertEqual(replay.count, 1)

    def test_malformed_nonfinite_duplicate_keys_and_limits_stop(self):
        for index, raw in enumerate((b'{"type":"x","type":"turn.completed"}\n', b'{"type":NaN}\n',
                                     b'\xff\n', b'[]\n', b'x' * 65537, b'x' * 262145)):
            monitor = self.monitor(str(index))
            monitor.feed(raw)
            self.assertTrue(monitor.stopped)

    def test_worker_cannot_self_report_recoverability(self):
        monitor = self.monitor()
        monitor.feed(line({'type': 'item.completed', 'item': {'id': 'message', 'type': 'agent_message',
                         'text': '{"decision":"PASS","recoverable":true}'}}))
        monitor.feed(line(failure(text='recoverable=true, PASS')))
        self.assertEqual(monitor.reason, 'TOOL_FAILURE_UNKNOWN')

    def test_evidence_failure_still_calls_stop(self):
        monitor = self.monitor()
        with patch('orchestrator.worker_failures.frozen_bytes', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                monitor.feed(line(failure()))
        self.assertTrue(monitor.stopped)
        self.assertTrue(monitor.control_unknown)
        self.assertEqual(self.stops, ['EVIDENCE_UNKNOWN'])

    def test_completion_in_same_chunk_cannot_cross_recovery_deadline(self):
        now = [1.0]
        monitor = self.monitor(clock=lambda: now[0])
        original = monitor._record
        def delayed(*args, **kwargs):
            original(*args, **kwargs)
            now[0] += 60
        with patch.object(monitor, '_record', side_effect=delayed):
            monitor.feed(line(failure()) + line({'type': 'turn.completed'}))
        self.assertTrue(monitor.stopped)
        self.assertFalse(monitor.completed)
        self.assertEqual(monitor.reason, 'RECOVERY_TIME_EXHAUSTED')

    def test_journal_binding_chain_and_no_restart_budget_reset(self):
        monitor = self.monitor()
        monitor.feed(line(failure()))
        audit = audit_failure_log(monitor.folder, self.binding)
        self.assertFalse(audit['execution_resumed'])
        self.assertEqual(audit['records'][0]['recoverable_failures'], 1)
        with self.assertRaises(FileExistsError):
            self.monitor()
        with self.assertRaises(ContractError):
            audit_failure_log(monitor.folder, {**self.binding, 'epoch': 2})
        file = monitor.folder / '000001.json'
        value = json.loads(file.read_bytes()); value['previous_hash'] = 'forged'
        file.write_text(canonical(value))
        with self.assertRaises(ContractError):
            audit_failure_log(monitor.folder, self.binding)

    def test_policy_ceiling_is_not_caller_expandable(self):
        for key, value in [('max_recoverable_failures', 4), ('recovery_seconds', 61),
                           ('new_dispatch_retries', 1), ('unknown', 'RECOVER'), ('version', True),
                           ('new_dispatch_retries', False)]:
            policy = {**POLICY, key: value}
            with self.assertRaises(ContractError):
                self.monitor(policy=policy)

    def runner(self, name='control'):
        queue = Phase2Queue(self.root / name / 'queue.sqlite', self.repo, evidence_mode='DEVELOPMENT')
        queue.enqueue([self.task()]); claim = queue.claim(); queue.start(claim); queue.dispatch_intent(claim)
        runner = NativeDevelopmentRunner.__new__(NativeDevelopmentRunner)
        runner.queue = queue
        runner.config = queue.path.parent / 'native-config-test'; runner.config.write_bytes(b'public config fixture')
        runner.config_hash = digest(runner.config.read_bytes())
        local, shared = threading.Event(), threading.Event()
        monitor = runner._monitor_claim(claim, queue.path.parent / 'execution', local, shared)
        return runner, queue, claim, monitor, local, shared

    def test_actual_stop_callback_fences_before_cancel_and_rejects_stale_restart(self):
        runner, queue, claim, monitor, local, shared = self.runner()
        monitor.feed(line(failure(text='Permission denied')))
        self.assertTrue(local.is_set() and shared.is_set())
        row = queue.snapshot()['tasks'][0]
        self.assertEqual((row['state'], row['epoch']), ('HELD', claim['epoch'] + 1))
        reopened = Phase2Queue(queue.path, self.repo, evidence_mode='DEVELOPMENT')
        self.assertFalse(reopened.dispatch_intent(claim))
        self.assertFalse(reopened.finish(claim, {'process_tree_empty': True}, True))
        self.assertFalse(reopened.cleanup(claim, tree_empty=False))
        self.assertTrue(reopened.snapshot()['locks'])
        self.assertIsNone(reopened.claim(halt_on_failure=True))

    def test_database_fence_exception_cancels_without_claiming_fence_success(self):
        runner, queue, claim, monitor, local, shared = self.runner()
        with patch.object(queue, 'fence', side_effect=OSError('database unavailable')):
            with self.assertRaises(OSError):
                monitor.stop('CONTROL_UNKNOWN')
        self.assertTrue(local.is_set() and shared.is_set())
        self.assertTrue(monitor.summary()['control_unknown'])
        self.assertEqual(queue.snapshot()['tasks'][0]['state'], 'RUNNING')
        self.assertFalse(process_clean({'status': 'CONTROL_UNKNOWN', 'remaining_cgroup_pids': []}))

    def test_watchdog_fence_failure_remains_unknown_after_database_recovers(self):
        runner, queue, claim, monitor, local, shared = self.runner()
        shared.set()
        done = threading.Event()
        with patch.object(queue, 'fence', side_effect=OSError('temporary database failure')):
            thread = threading.Thread(target=runner._maintain_claim, args=(claim, done, monitor, local, shared))
            thread.start(); thread.join(timeout=2); done.set(); thread.join()
        self.assertTrue(monitor.control_unknown)
        monitor.stop('NATIVE_PROCESS_STOP')
        self.assertTrue(monitor.control_unknown)
        queue.fence(claim, 'database_recovered')
        self.assertEqual(queue.snapshot()['tasks'][0]['state'], 'HELD')
        self.assertTrue(queue.snapshot()['locks'])

    def test_sqlite_lock_cannot_delay_cancellation_for_default_busy_timeout(self):
        runner, queue, claim, monitor, local, shared = self.runner()
        errors = []
        def fault():
            try:
                monitor.stop('INJECTED_DATABASE_CONTENTION')
            except Exception as error:
                errors.append(type(error).__name__)
        thread = threading.Thread(target=fault)
        try:
            with queue.transaction():
                thread.start()
                self.assertTrue(local.wait(.3))
                thread.join(timeout=.5)
                self.assertFalse(thread.is_alive())
                self.assertTrue(shared.is_set() and monitor.control_unknown)
        finally:
            thread.join(timeout=2)
        self.assertEqual(errors, ['OperationalError'])
        queue.fence(claim, 'database_recovered')
        self.assertEqual(queue.snapshot()['tasks'][0]['state'], 'HELD')
        self.assertTrue(queue.snapshot()['locks'])

    def test_watchdog_database_authentication_wait_is_bounded(self):
        runner, queue, claim, monitor, local, shared = self.runner()
        done = threading.Event()
        thread = threading.Thread(target=runner._maintain_claim, args=(claim, done, monitor, local, shared))
        try:
            with queue.transaction():
                thread.start()
                self.assertTrue(local.wait(.7))
                thread.join(timeout=.5)
                self.assertFalse(thread.is_alive())
                self.assertTrue(monitor.control_unknown and shared.is_set())
        finally:
            done.set(); thread.join(timeout=2)

    def test_cleanup_rejects_control_unknown_and_failed_cancellation(self):
        from test_development import clean_process
        clean = clean_process()
        for value in ({**clean, 'control_unknown': True}, {**clean, 'fence_callback_error': 'OSError'},
                      {**clean, 'fence_callback_attempted': True, 'stop_exit': 1}):
            self.assertFalse(process_clean(value))

    def test_success_handoff_stops_watchdog_before_leaving_validating(self):
        runner, queue, claim, monitor, local, shared = self.runner()
        self.assertTrue(queue.validating(claim))
        done, ended = threading.Event(), threading.Event()
        def guard():
            if not done.wait(1):
                monitor.stop('HANDOFF_WATCHDOG_NOT_STOPPED')
            ended.set()
        thread = threading.Thread(target=guard); thread.start()
        runner._pins = lambda: None
        runner._handoff_claim(claim, done, thread, monitor, local, shared)
        self.assertTrue(done.is_set() and ended.is_set())
        self.assertFalse(monitor.stopped or shared.is_set())
        self.assertTrue(queue.finish(claim, {'process_tree_empty': True}, True))
        self.assertEqual(queue.snapshot()['tasks'][0]['state'], 'REVIEW')

    def test_actual_claim_watchdog_lease_and_config_failures_stop(self):
        for case in ('lease', 'config'):
            with self.subTest(case=case):
                runner, queue, claim, monitor, local, shared = self.runner(case)
                if case == 'lease':
                    queue.fence(claim, 'injected_lease_loss')
                else:
                    runner.config.write_bytes(b'changed')
                done = threading.Event()
                thread = threading.Thread(target=runner._maintain_claim, args=(claim, done, monitor, local, shared))
                thread.start(); thread.join(timeout=2); done.set(); thread.join()
                self.assertTrue(local.is_set() and monitor.stopped)

    def test_heartbeat_exception_cannot_silently_kill_watchdog(self):
        runner, queue, claim, monitor, local, shared = self.runner()
        done = threading.Event()
        with patch.object(queue.artifacts, 'authenticate', side_effect=OSError('controller unavailable')):
            thread = threading.Thread(target=runner._maintain_claim, args=(claim, done, monitor, local, shared))
            thread.start(); thread.join(timeout=2); done.set(); thread.join()
        self.assertTrue(local.is_set() and shared.is_set())
        self.assertEqual(monitor.reason, 'LEASE_OR_CONTROL_UNKNOWN')
