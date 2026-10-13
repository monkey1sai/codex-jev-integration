"""Synthetic RPC secrets must not escape into native admission evidence."""
import hashlib
import io
import json
import unittest
from unittest.mock import patch

from tools.development_validator import execute, public_response


class ValidatorRedactionTests(unittest.TestCase):
    def test_rpc_execution_never_persists_config_or_thread_secrets(self):
        secret = 'SYNTHETIC_NOT_A_REAL_CREDENTIAL'
        filesystem = {':minimal': 'read'}
        config = {'default_permissions': 'worker-minimal', 'approval_policy': 'never',
                  'model': 'gpt-6-astra', 'model_reasoning_effort': 'high',
                  'approvals_reviewer': 'auto_review',
                  'permissions': {'worker-minimal': {'network': {'enabled': False, 'private': secret},
                                                    'filesystem': filesystem, 'private': secret},
                                  'unused-profile': {'private': secret}},
                  'provider_private_value': secret,
                  'shell_environment_policy': {'set': {'PRIVATE_VALUE': secret}},
                  'mcp_servers': {'fixture': {'env': {'PRIVATE_VALUE': secret}}}}
        replies = [
            {'id': 1, 'result': {'userAgent': 'fixture', 'private': secret}},
            {'id': 2, 'result': {'config': config, 'layers': [{'private': secret}]}},
            {'id': 4, 'result': {'model': 'gpt-6-astra', 'reasoningEffort': 'high',
                'approvalPolicy': 'never', 'approvalsReviewer': 'auto_review',
                'thread': {'id': 'fixture-thread', 'turns': [{'private': secret}]}}},
            {'id': 3, 'result': {'exitCode': 0, 'stdout': 'accepted', 'stderr': ''}},
        ]
        class Process:
            stdin = io.StringIO()
            stdout = io.StringIO('\n'.join(json.dumps(x) for x in replies) + '\n')
            returncode = 0
            def wait(self, timeout):
                return self.returncode
        plan = {'server_argv': ['never-start-a-process'], 'workspace': '.',
                'plan_hash': 'fixture', 'expected_filesystem': filesystem,
                'check_thread_start': True,
                'command': {'argv': ['fixture-only'], 'timeout_seconds': 1}}
        output = io.StringIO()
        with patch('tools.development_validator.subprocess.Popen', return_value=Process()), \
                patch('sys.stdout', output):
            self.assertEqual(execute(plan), 0)
        raw = output.getvalue()
        self.assertNotIn(secret, raw)
        result = json.loads(raw)
        self.assertEqual(result['status'], 'PASS')
        summary = result['effective_config']['permission_summary']
        self.assertIs(summary['network_enabled'], False)
        self.assertEqual(summary['filesystem_sha256'], hashlib.sha256(
            json.dumps(filesystem, sort_keys=True, separators=(',', ':')).encode()).hexdigest())
        started = next(x['result'] for x in result['trace'] if x.get('id') == 4 and 'result' in x)
        self.assertEqual(started['model'], 'gpt-6-astra')
        self.assertEqual(started['reasoningEffort'], 'high')
        self.assertEqual(result['native_session_start']['thread_id'], 'fixture-thread')
        self.assertEqual(result['result']['stdout'], 'accepted')

    def test_rpc_error_never_retains_message_or_data(self):
        value = public_response('config/read', {'id': 2, 'error': {
            'code': -1, 'message': 'SYNTHETIC_PRIVATE_MESSAGE',
            'data': {'token': 'SYNTHETIC_PRIVATE_DATA'}}})
        self.assertEqual(value, {'id': 2, 'error': {'classification': 'NATIVE_RPC_REJECTED'}})


if __name__ == '__main__':
    unittest.main()
