import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).parent / 'payload/jev/decision.py'
spec = importlib.util.spec_from_file_location('decision', MODULE)
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


def answer(choice='research', confidence=1):
    return {'model': 'jev-test', 'answers': {'route': {'type': 'choice', 'choice': choice, 'confidence': confidence,
        'probabilities': {k: int(k == choice) for k in d.ROLES}}}}


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.global_path = self.root / 'global.json'
        self.global_path.write_text(json.dumps({'enabled': True, 'confidence_threshold': 0.8, 'timeout_seconds': 20}))
        (self.root / '.codex').mkdir()
        self.args = {'workspace': str(self.root), 'task_summary': 'Read official docs about an API.'}

    def test_local_override_is_separate_and_fresh(self):
        before = self.global_path.read_bytes()
        local = self.root / '.codex/jev.json'
        local.write_text('{"timeout_seconds": 5, "confidence_threshold": 0.9}')
        config = d.effective_config(str(self.root), self.global_path)
        self.assertEqual((config['timeout_seconds'], config['confidence_threshold']), (5, 0.9))
        local.write_text('{"enabled": false}')
        self.assertFalse(d.effective_config(str(self.root), self.global_path)['enabled'])
        self.assertEqual(before, self.global_path.read_bytes())

    def test_disabled_never_calls_provider_but_gates_survive(self):
        (self.root / '.codex/jev.json').write_text('{"enabled": false}')
        def forbidden(*args):
            self.fail('Disabled/gate called provider')
        self.assertEqual(d.route(self.args, self.global_path, forbidden)['reason'], 'JEV_DISABLED')
        for extra in [{'stage': 'before_delivery'}, {'stage': 'before_plan', 'large_plan': True}, {'failure_count': 2}]:
            result = d.route({**self.args, **extra}, self.global_path, forbidden)
            self.assertEqual((result['model'], result['reasoning_effort'], result['required_review']), ('gpt-6-astra', 'high', True))

    def test_gate_survives_broken_config_and_missing_workspace(self):
        self.global_path.write_text('malformed')
        result = d.route({**self.args, 'workspace': 'missing', 'stage': 'before_delivery'}, self.global_path)
        self.assertTrue(result['required_review'])

    def test_fallback_errors_and_low_confidence(self):
        for error in ['AUTH_MISSING', 'HTTP_401', 'HTTP_429', 'NETWORK_OR_TIMEOUT', 'INVALID_RESPONSE', 'REDIRECT_REJECTED']:
            def fail(*args):
                raise d.SafeFailure(error)
            result = d.route(self.args, self.global_path, fail)
            self.assertEqual((result['route'], result['reason'], result['executed']), ('coordinate', error, False))
        result = d.route(self.args, self.global_path, lambda *args: {'choice': 'implement', 'confidence': 0.2})
        self.assertEqual(result['reason'], 'LOW_CONFIDENCE')

    def test_validated_response_rejects_tampering(self):
        self.assertEqual(d.validate_answer(answer())['choice'], 'research')
        for field, value in [('choice', 'shell'), ('confidence', True), ('confidence', float('nan')),
                             ('probabilities', {'research': 1}), ('type', 'noul')]:
            invalid = answer()
            invalid['answers']['route'][field] = value
            with self.assertRaises(d.SafeFailure):
                d.validate_answer(invalid)
        invalid = answer()
        invalid['answers']['route']['probabilities']['implement'] = 1
        with self.assertRaises(d.SafeFailure):
            d.validate_answer(invalid)

    def test_invalid_settings_fail_closed(self):
        for config in [{'enabled': 'false'}, {'endpoint': 'https://other.test'}, {'timeout_seconds': 21},
                       {'timeout_seconds': True}, {'confidence_threshold': float('inf')}]:
            (self.root / '.codex/jev.json').write_text(json.dumps(config))
            result = d.route(self.args, self.global_path, lambda *args: self.fail('Invalid config called provider'))
            self.assertEqual(result['route'], 'coordinate')

    def test_invalid_route_args_do_not_call_provider(self):
        for extra in [{'failure_count': True}, {'large_plan': 1}, {'stage': 'approve'}, {'task_summary': 'x' * 4001}, {'unknown': 1}]:
            with self.assertRaises(d.SafeFailure):
                d.route({**self.args, **extra}, self.global_path, lambda *args: self.fail('Invalid args called provider'))

    def test_no_redirect_even_for_authorization_header(self):
        with self.assertRaises(d.SafeFailure):
            d.NoRedirect().redirect_request(None, None, 302, '', None, 'https://other.test')

    def test_mcp_handshake_status_and_disabled_route(self):
        (self.root / '.codex/jev.json').write_text('{"enabled": false}')
        messages = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2024-11-05'}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'jev_status', 'arguments': {'workspace': str(self.root)}}},
            {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'jev_route', 'arguments': self.args}},
        ]
        result = subprocess.run([sys.executable, '-B', str(MODULE), 'serve', '--config', str(self.global_path)],
            input='\n'.join(json.dumps(m) for m in messages) + '\n', text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(len(responses), 4)
        self.assertEqual([tool['name'] for tool in responses[1]['result']['tools']], ['jev_status', 'jev_route', 'jev_report_outcome', 'jev_select_resources', 'jev_decide', 'jev_report_selection_outcome'])
        status = json.loads(responses[2]['result']['content'][0]['text'])
        self.assertFalse(status['effective_config']['enabled'])
        self.assertEqual(json.loads(responses[3]['result']['content'][0]['text'])['reason'], 'JEV_DISABLED')

    def test_http_body_never_exposed(self):
        import io
        error = d.urllib.error.HTTPError(d.ENDPOINT, 401, 'SECRET_RESPONSE', {}, io.BytesIO(b'SECRET_RESPONSE'))
        with patch.object(d, 'api_key', return_value='FAKE_TEST_KEY'), patch.object(d.urllib.request.OpenerDirector, 'open', side_effect=error):
            with self.assertRaises(d.SafeFailure) as caught:
                d.evaluate('synthetic', {'timeout_seconds': 1})
        self.assertEqual(str(caught.exception), 'HTTP_401')


if __name__ == '__main__':
    unittest.main()
