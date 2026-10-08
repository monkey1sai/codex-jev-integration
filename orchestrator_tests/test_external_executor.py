"""Offline guards, never evidence that a release tool ran in containment."""
import io
import json
from pathlib import Path
import tempfile
import unittest

from tools.external_executor_poc import (POLICY, Rpc, digest, open_bootstrap_gate,
                                         outer_argv, validate_boundary, final_verdict, filesystem_denied)


def measurement():
    # A synthetic measurement is used only for rejection/ordering tests.
    points = [('/', 'tmpfs', 'ro'), ('/usr', 'ext4', 'ro'),
              ('/runtime/codex', 'ext4', 'ro'), ('/gate.py', 'ext4', 'ro'),
              ('/workspace', 'ext4', 'rw'), ('/workspace/.git', 'ext4', 'ro'),
              ('/scratch', 'tmpfs', 'rw'), ('/proc', 'proc', 'rw'), ('/dev', 'tmpfs', 'rw')]
    mounts = '\n'.join(f'{i+1} 0 0:{i+5} / {p} {mode} - {fs} {fs} {mode}'
                       for i, (p, fs, mode) in enumerate(points))
    return {'namespaces': {n: n+':[12]' for n in ('mnt', 'pid', 'net', 'user')},
        'controller_namespaces': {n: n+':[11]' for n in ('mnt', 'pid', 'net', 'user')},
        'exe_sha256': 'a'*64, 'expected_exe_sha256': 'a'*64, 'policy_sha256': digest(POLICY),
        'mountinfo': mounts, 'workspace_identity': [4, 5], 'host_workspace_identity': [4, 5],
        'visible_forbidden_paths': [], 'network': {'namespace': 'net:[12]', 'uid': 1000,
            'interfaces': ['lo'], 'route': 'Iface\tDestination\n', 'ipv6_route': '',
            'cap_eff': '0000000000000000', 'no_new_privs': '1'}}


class ExternalExecutor(unittest.TestCase):
    def test_gate_requires_independent_namespace_for_every_boundary(self):
        for n in ('mnt', 'pid', 'net', 'user'):
            value = measurement(); value['namespaces'][n] = value['controller_namespaces'][n]
            with self.subTest(n=n), self.assertRaises(ValueError):
                validate_boundary(value)

    def test_unknown_mounts_fail_before_bootstrap_can_start_cli(self):
        for raw in ('', 'invalid mount'):
            with tempfile.TemporaryDirectory() as folder:
                stream = io.BytesIO(); value = measurement(); value['mountinfo'] = raw
                with self.assertRaises(ValueError):
                    open_bootstrap_gate(value, Path(folder), 'test', stream)
                self.assertEqual(stream.getvalue(), b'')
                self.assertFalse((Path(folder)/'pre-execution-gate.json').exists())

    def test_policy_mismatch_never_opens_gate(self):
        with tempfile.TemporaryDirectory() as folder:
            stream = io.BytesIO(); value = measurement(); value['policy_sha256'] = 'b'*64
            with self.assertRaises(ValueError):
                open_bootstrap_gate(value, Path(folder), 'test', stream)
            self.assertEqual(stream.getvalue(), b'')

    def test_gate_durable_receipt_precedes_permission_byte_and_rejects_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder); value = measurement()
            class Observer(io.BytesIO):
                def write(self, data):
                    record = json.loads((path/'pre-execution-gate.json').read_text())
                    self.test.assertEqual(record['challenge'], 'challenge')
                    return super().write(data)
            stream = Observer(); stream.test = self
            open_bootstrap_gate(value, path, 'challenge', stream)
            self.assertEqual(stream.getvalue(), b'G')
            replay = io.BytesIO()
            with self.assertRaises(FileExistsError):
                open_bootstrap_gate(value, path, 'challenge', replay)
            self.assertEqual(replay.getvalue(), b'')

    def test_readonly_git_and_runtime_cannot_be_weakened(self):
        for p in ('/workspace/.git', '/runtime/codex', '/usr', '/gate.py'):
            value = measurement(); value['mountinfo'] = value['mountinfo'].replace(p+' ro', p+' rw')
            with self.subTest(p=p), self.assertRaises(ValueError):
                validate_boundary(value)

    def test_unexpected_host_write_carveout_and_propagation_rejected(self):
        value = measurement(); value['mountinfo'] += '\n100 1 8:2 / /escape rw - ext4 /dev/sda rw'
        with self.assertRaises(ValueError): validate_boundary(value)
        value = measurement(); value['mountinfo'] = value['mountinfo'].replace('/ ro -', '/ ro shared:1 -', 1)
        with self.assertRaises(ValueError): validate_boundary(value)

    def test_workspace_inode_mismatch_rejected(self):
        value = measurement(); value['workspace_identity'] = [9, 9]
        with self.assertRaises(ValueError): validate_boundary(value)

    def test_protected_host_paths_must_be_invisible(self):
        value = measurement(); value['visible_forbidden_paths'] = ['/mnt/c']
        with self.assertRaises(ValueError): validate_boundary(value)

    def test_network_root_capability_and_nnp_fail_closed(self):
        for k, v in [('interfaces', ['lo', 'eth0']), ('uid', 0), ('cap_eff', '0000000000000001'),
                     ('no_new_privs', '0'), ('route', 'Iface\tDestination\neth0\t00000000')]:
            value = measurement(); value['network'][k] = v
            with self.subTest(k=k), self.assertRaises(ValueError): validate_boundary(value)

    def test_binary_mismatch_rejected(self):
        value = measurement(); value['exe_sha256'] = 'b'*64
        with self.assertRaises(ValueError): validate_boundary(value)

    def test_unlisted_method_does_not_write_to_peer(self):
        rpc = object.__new__(Rpc)
        with self.assertRaisesRegex(ValueError, 'UNLISTED_RPC'):
            rpc.call('http/request', {})

    def test_outer_mounts_never_include_controller_or_credentials(self):
        args = outer_argv(Path('/runtime-host'), Path('/run-owned'), 8, 'challenge')
        self.assertIn('--unshare-net', args)
        self.assertIn('--unshare-pid', args)
        self.assertNotIn('--share-net', args)
        self.assertNotIn('/run-owned/credentials', args)
        self.assertNotIn('/run-owned/controller', args)
        self.assertNotIn('/runtime-host/runtime-home', args)
        self.assertEqual(args[args.index('--info-fd')+1], '8')

    def test_successful_rpc_cannot_mask_lifecycle_or_resource_failure(self):
        report = {'status': 'EXEC_SERVER_SUBSET_VERIFIED', 'server_exit': 0,
                  'stderr_limit_exceeded': False, 'stderr_reader_closed': True}
        execution = {'status': 'EXITED', 'exit_code': 0, 'output_limit_exceeded': False,
                     'remaining_cgroup_pids': [], 'output_readers_closed': True,
                     'kernel_resource_limits': {'memory.max': '1073741824',
                                                'memory.swap.max': '0', 'pids.max': '64'}}
        self.assertEqual(final_verdict(report, execution, ['mathutil.py']), 'EXEC_SERVER_SUBSET_VERIFIED')
        for key, value in [('status', 'CLEANUP_UNVERIFIED'), ('exit_code', 1), ('output_limit_exceeded', True),
                           ('remaining_cgroup_pids', ['999']), ('output_readers_closed', False),
                           ('kernel_resource_limits', None)]:
            with self.subTest(key=key):
                self.assertEqual(final_verdict(report, {**execution, key: value}, ['mathutil.py']), 'BLOCKED')
        self.assertEqual(final_verdict({**report, 'stderr_limit_exceeded': True}, execution, ['mathutil.py']), 'BLOCKED')
        self.assertEqual(final_verdict(report, execution, ['mathutil.py', '.git/config']), 'BLOCKED')

    def test_protocol_error_is_not_filesystem_denial(self):
        for code in (-32600, -32601, -32602):
            self.assertFalse(filesystem_denied({'error': {'code': code, 'message': 'Permission denied'}}))
        self.assertFalse(filesystem_denied({'error': {'code': -32000, 'message': 'Unknown request'}}))
        self.assertTrue(filesystem_denied({'error': {'code': -32000, 'message': 'Read-only file system (os error 30)'}}))


if __name__ == '__main__':
    unittest.main()
