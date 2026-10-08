"""Deterministic rejection guards; these tests never launch a worker or provider."""
import copy
import errno
import json
from pathlib import Path
import tempfile
import unittest

from tools.linux_worker_smoke import check_add_artifact, check_canaries, check_lifecycle, check_resource_limits, tree


class LinuxSmokeGuards(unittest.TestCase):
    def test_property_or_missing_kernel_limits_cannot_approve_runtime(self):
        expected = {'memory.max': '1073741824', 'memory.swap.max': '0', 'pids.max': '64'}
        check_resource_limits(expected)
        for value in (None, {}, {'MemoryMax': '1073741824', 'TasksMax': '64'},
                      {**expected, 'memory.max': 'max'}, {**expected, 'pids.max': 'max'}):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, 'KERNEL_RESOURCE_LIMITS_UNVERIFIED'):
                    check_resource_limits(value)

    def test_import_exit_spoof_and_other_executable_constructs_rejected(self):
        check_add_artifact(b'def add(a, b):\n    return a + b\n')
        for source in (b'import os\nos.write(1, b"ACCEPTANCE_PASS\\n")\nos._exit(0)\n',
                       b'@print("SIDE_EFFECT")\ndef add(a,b):\n    return a+b\n',
                       b'def add(a,b=print("SIDE_EFFECT")):\n    return a+b\n',
                       b'def add(a,b):\n    return a-b\n'):
            with self.subTest(source=source):
                with self.assertRaises(ValueError):
                    check_add_artifact(source)

    def test_exit_zero_does_not_approve_access_or_network_timeout(self):
        base = {name: {'access': 'ALLOWED'} for name in ('workspace_read', 'workspace_write', 'git_read')}
        base['controller_read'] = {'access': 'ALLOWED'}
        evidence = {'real_canary': {'result': {'exitCode': 0, 'stdout': json.dumps(base)}},
                    'extended_canary': {'result': {'exitCode': 0, 'stdout': '{}'}}}
        with self.assertRaisesRegex(ValueError, 'FILESYSTEM_CANARY_FAILED:controller_read'):
            check_canaries(evidence)
        for name in ('controller_read', 'controller_write', 'credential_home_read',
                     'credential_home_write', 'other_worktree_read', 'other_worktree_write',
                     'proc_host_root', 'windows_controller_read'):
            base[name] = {'access': 'DENIED', 'errno': 2, 'reason': 'No such file or directory'}
        base['network'] = {'access': 'DENIED', 'errno': errno.ETIMEDOUT}
        evidence['real_canary']['result']['stdout'] = json.dumps(base)
        with self.assertRaisesRegex(ValueError, 'NETWORK_ENFORCEMENT_NOT_PROVEN:network'):
            check_canaries(evidence)

    def test_duplicate_lifecycle_or_wrong_config_is_rejected(self):
        item = {'case': 'cancel', 'status': 'PASS', 'remaining_after_final_cleanup': []}
        record = {'config_sha256': 'frozen', 'cases': [copy.deepcopy(item) for _ in range(3)]}
        with self.assertRaisesRegex(ValueError, 'LIFECYCLE_CASES_REQUIRED'):
            check_lifecycle(record, 'frozen')
        record['cases'][1]['case'] = 'timeout'
        record['cases'][2]['case'] = 'controller_interruption'
        check_lifecycle(record, 'frozen')
        with self.assertRaisesRegex(ValueError, 'CURRENT_LIFECYCLE_EVIDENCE_REQUIRED'):
            check_lifecycle(record, 'drifted')

    def test_host_snapshot_bounds_count_and_size_before_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with (root/'oversized').open('wb') as out:
                out.truncate(1048577)
            with self.assertRaisesRegex(ValueError, 'TREE_FILE_LIMIT'):
                tree(root)
            (root/'oversized').unlink()
            for number in range(257):
                (root/str(number)).write_bytes(b'')
            with self.assertRaisesRegex(ValueError, 'TREE_COUNT_LIMIT'):
                tree(root)
