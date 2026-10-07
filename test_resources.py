import copy
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).parent / 'payload/jev/decision.py'
spec = importlib.util.spec_from_file_location('resource_candidate', MODULE)
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


def candidate(identity, kind, **updates):
    return {'id': identity, 'kind': kind, 'description': 'Public capability description',
            'available': True, 'in_scope': True, **updates}


def response(body, choices=None, confidence=.95):
    choices = choices or {}
    return {'model': 'jev-test', 'answers': {
        kind: {'type': 'choice', 'choice': choices.get(kind, next(iter(question['criteria']))),
               'confidence': confidence, 'probabilities': {
                   identity: int(identity == choices.get(kind, next(iter(question['criteria']))))
                   for identity in question['criteria']}}
        for kind, question in body['questions'].items()},
        'usage': {'input_tokens': 10, 'output_tokens': 3}}


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'config.json'
        self.config.write_text(json.dumps({'enabled': True, 'confidence_threshold': .8, 'timeout_seconds': 20}))
        self.args = {'workspace': str(self.root), 'task_summary': 'Choose a capability for a public task.',
                     'candidates': [candidate('read_files', 'tool'), candidate('browser_ui', 'mcp'), candidate('research', 'skill')]}

    def forbidden(self, *_):
        self.fail('Unexpected provider request')

    def test_one_request_selects_three_kinds_without_execution(self):
        calls = []
        def fake(body, config):
            calls.append(body)
            return response(body)
        result = d.select_resources(self.args, self.config, fake)
        self.assertEqual(len(calls), 1)
        self.assertEqual({i['id'] for i in result['selected']}, {'read_files', 'browser_ui', 'research'})
        self.assertTrue(result['advisory_only'])
        self.assertFalse(result['executed'])
        self.assertEqual(result['inventory_source'], 'caller_reported')
        self.assertEqual(result['observation']['status'], 'not_recorded')
        self.assertEqual(set(calls[0]['state']), {'task_summary'})
        self.assertFalse((self.root/'audit').exists())

    def test_unavailable_out_of_scope_excluded_before_provider(self):
        self.args['candidates'] += [candidate('offline', 'skill', available=False), candidate('blocked', 'tool', in_scope=False)]
        def fake(body, config):
            options = set().union(*(set(q['criteria']) for q in body['questions'].values()))
            self.assertNotIn('offline', options)
            self.assertNotIn('blocked', options)
            return response(body)
        self.assertEqual(d.select_resources(self.args, self.config, fake)['status'], 'selected')

    def test_no_candidates_does_not_request_or_discover(self):
        for entries in ([], [candidate('offline', 'tool', available=False)]):
            result = d.select_resources({**self.args, 'candidates': entries}, self.config, self.forbidden)
            self.assertEqual(result['reason'], 'NO_ELIGIBLE_CANDIDATES')
            self.assertEqual(result['selected'], [])
            self.assertFalse(result['provider_called'])

    def test_multiple_explicit_resources_of_same_kind_preserved(self):
        self.args['candidates'] += [candidate('second_skill', 'skill')]
        self.args['required_ids'] = ['read_files', 'browser_ui', 'research', 'second_skill']
        result = d.select_resources(self.args, self.config, self.forbidden)
        self.assertEqual({i['id'] for i in result['selected']}, set(self.args['required_ids']))
        self.assertTrue(all(i['source'] == 'required' for i in result['selected']))
        self.assertFalse(result['provider_called'])

    def test_required_kind_not_replaced_by_model(self):
        self.args['required_ids'] = ['research']
        def fake(body, config):
            self.assertNotIn('skill', body['questions'])
            return response(body)
        result = d.select_resources(self.args, self.config, fake)
        self.assertEqual(result['selected'][0], {'id': 'research', 'kind': 'skill', 'source': 'required'})

    def test_candidate_inventory_changes_per_call_without_static_names(self):
        calls = []
        def fake(body, config):
            calls.append(body)
            return response(body)
        first = d.select_resources(self.args, self.config, fake)
        updated = {**self.args, 'candidates':[candidate('new_tool','tool'), candidate('new_mcp','mcp'),
                                              candidate('new_skill','skill'), candidate('browser_ui','mcp',available=False)]}
        second = d.select_resources(updated, self.config, fake)
        self.assertEqual({row['id'] for row in first['selected']}, {'read_files','browser_ui','research'})
        self.assertEqual({row['id'] for row in second['selected']}, {'new_tool','new_mcp','new_skill'})
        second_ids = set().union(*(set(q['criteria']) for q in calls[1]['questions'].values()))
        self.assertNotIn('read_files', second_ids)
        self.assertNotIn('browser_ui', second_ids)

    def test_provider_cannot_select_id_from_previous_inventory(self):
        self.args['candidates'] = [candidate('current_tool','tool')]
        def stale(body, config):
            wire = response(body)
            wire['answers']['tool']['choice'] = 'read_files'
            return wire
        result = d.select_resources(self.args, self.config, stale)
        self.assertEqual(result['reason'], 'INVALID_RESOURCE_RESPONSE')
        self.assertEqual(result['selected'], [])

    def test_required_but_unavailable_stops_before_provider(self):
        self.args['required_ids'] = ['research']
        self.args['candidates'][2]['available'] = False
        result = d.select_resources(self.args, self.config, self.forbidden)
        self.assertEqual(result['reason'], 'REQUIRED_RESOURCE_UNAVAILABLE')
        self.assertEqual(result['selected'], [])

    def test_none_and_low_confidence_do_not_select_optional_resources(self):
        for fake in (lambda body, config: response(body, {kind: 'none' for kind in body['questions']}),
                     lambda body, config: response(body, confidence=.2)):
            result = d.select_resources(self.args, self.config, fake)
            self.assertEqual(result['selected'], [])
            self.assertFalse(result['executed'])

    def test_review_gates_precede_config_and_provider(self):
        self.config.write_text('malformed')
        for gate in ({'failure_count': 2}, {'stage': 'before_plan', 'large_plan': True}, {'stage': 'before_delivery'}):
            result = d.select_resources({**self.args, **gate}, self.config, self.forbidden)
            self.assertTrue(result['required_review'])
            self.assertFalse(result['provider_called'])
            self.assertEqual(result['selected'], [])
        result = d.select_resources({**self.args, 'stage': 'before_delivery', 'risk_level': 'bounded'}, self.config, self.forbidden)
        self.assertEqual(result['reason'], 'LOCAL_VERIFICATION_REQUIRED')

    def test_disabled_and_invalid_configuration_fail_without_provider(self):
        for data in ({'enabled': False}, {'endpoint': 'https://untrusted.invalid'}, {'confidence_threshold': True}):
            self.config.write_text(json.dumps(data))
            result = d.select_resources(self.args, self.config, self.forbidden)
            self.assertEqual(result['status'], 'fallback')
            self.assertFalse(result['provider_called'])

    def test_invalid_candidate_fields_and_id_injection_rejected(self):
        bad = [candidate('none', 'tool'), candidate('../escape', 'tool'), candidate('x', 'shell'),
               candidate('x', 'tool', description=''), candidate('x', 'tool', description='x'*241),
               candidate('x', 'tool', available='true'), candidate('x', 'tool', in_scope=1),
               {**candidate('x','tool'), 'command':'execute'}, {'id':'x'}]
        for item in bad:
            with self.subTest(item=item), self.assertRaises(d.SafeFailure):
                d.select_resources({**self.args,'candidates':[item]}, self.config, self.forbidden)

    def test_duplicate_limits_required_ids_and_unknown_arguments_rejected(self):
        for extra in ({'candidates':[candidate('same','tool'),candidate('same','mcp')]},
                      {'candidates':[candidate('x'+str(i),'tool') for i in range(25)]},
                      {'required_ids':['missing']}, {'required_ids':['research','research']},
                      {'required_ids':[False]}, {'requester':'injection'}, {'risk_level':'autoapprove'}):
            with self.subTest(extra=extra), self.assertRaises(d.SafeFailure):
                d.select_resources({**self.args,**extra}, self.config, self.forbidden)

    def test_invalid_provider_choice_distribution_and_model_fail_closed(self):
        for tamper in ('id', 'probabilities', 'bool', 'nan', 'model', 'extra_question', 'missing_question'):
            def fake(body, config):
                wire = response(body)
                if tamper == 'id': wire['answers']['tool']['choice']='execute_shell'
                if tamper == 'probabilities': wire['answers']['tool']['probabilities']['blocked']=1
                if tamper == 'bool': wire['answers']['tool']['confidence']=True
                if tamper == 'nan': wire['answers']['tool']['confidence']=float('nan')
                if tamper == 'model': wire['model']='untrusted'
                if tamper == 'extra_question': wire['answers']['approve']={}
                if tamper == 'missing_question': del wire['answers']['skill']
                return wire
            result=d.select_resources(self.args,self.config,fake)
            self.assertEqual(result['reason'],'INVALID_RESOURCE_RESPONSE')
            self.assertEqual(result['selected'],[])

    def test_provider_failure_keeps_required_resources_no_retry_or_error_echo(self):
        self.args['required_ids']=['research']
        calls=[]
        def fail(body, config):
            calls.append(True)
            raise d.SafeFailure('NETWORK_OR_TIMEOUT')
        result=d.select_resources(self.args,self.config,fail)
        self.assertEqual(len(calls),1)
        self.assertEqual(result['selected'],[{'id':'research','kind':'skill','source':'required'}])
        self.assertEqual(result['reason'],'NETWORK_OR_TIMEOUT')

    def test_raw_provider_fields_are_never_returned(self):
        def fake(body, config):
            wire=response(body)
            wire['command']='secret marker'
            for answer in wire['answers'].values(): answer['instructions']='secret marker'
            return wire
        result=d.select_resources(self.args,self.config,fake)
        self.assertNotIn('secret marker',json.dumps(result))

    def test_huge_json_numbers_fail_closed_in_resources_roles_and_config(self):
        self.args['required_ids'] = ['research']
        for field in ('confidence', 'probabilities'):
            def fake(body, config):
                wire = response(body)
                if field == 'confidence': wire['answers']['tool']['confidence'] = 10**1000
                else: wire['answers']['tool']['probabilities']['read_files'] = 10**1000
                return json.loads(json.dumps(wire))
            result = d.select_resources(self.args, self.config, fake)
            self.assertEqual(result['reason'], 'INVALID_RESOURCE_RESPONSE')
            self.assertEqual(result['selected'], [{'id':'research','kind':'skill','source':'required'}])
        role_body = {'questions': {'route': {'criteria': d.ROLES}}}
        for field in ('confidence', 'probabilities'):
            wire = response(role_body)
            if field == 'confidence': wire['answers']['route']['confidence'] = 10**1000
            else: wire['answers']['route']['probabilities']['coordinate'] = 10**1000
            with self.assertRaisesRegex(d.SafeFailure, 'INVALID_RESPONSE'):
                d.validate_answer(wire)
        for field in ('confidence_threshold', 'timeout_seconds'):
            with self.assertRaisesRegex(d.SafeFailure, 'INVALID_CONFIG_NUMBER'):
                d.validate_config({field: 10**1000})

    def test_stdio_survives_huge_provider_number_and_keeps_required(self):
        self.args['required_ids'] = ['research']
        def fake(body, config):
            wire = response(body)
            wire['answers']['tool']['confidence'] = 10**1000
            return wire
        messages = [{'id':1, 'method':'tools/call', 'params':{'name':'jev_select_resources','arguments':self.args}},
                    {'id':2, 'method':'ping'}]
        source = type('Input', (), {'buffer':io.BytesIO(''.join(json.dumps(m)+'\n' for m in messages).encode())})()
        output = io.StringIO()
        with patch.object(d, 'request_questions', fake), patch.object(d.sys, 'stdin', source), contextlib.redirect_stdout(output):
            d.serve(self.config)
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        result = json.loads(rows[0]['result']['content'][0]['text'])
        self.assertEqual(result['reason'], 'INVALID_RESOURCE_RESPONSE')
        self.assertEqual(result['selected'], [{'id':'research','kind':'skill','source':'required'}])
        self.assertEqual(rows[1]['result'], {})

    def test_shared_transport_caps_request_before_credentials(self):
        with patch.object(d,'api_key',side_effect=AssertionError('credential access')):
            with self.assertRaisesRegex(d.SafeFailure,'REQUEST_TOO_LARGE'):
                d.request_questions({'state':'x'*(d.MAX_BYTES+1)}, {'timeout_seconds':20})

    def test_mcp_and_cli_register_and_call_new_tool_without_inference(self):
        self.config.write_text('{"enabled":false}')
        inputs={**self.args,'required_ids':['read_files','browser_ui','research']}
        messages=[{'jsonrpc':'2.0','id':1,'method':'initialize'},
                  {'jsonrpc':'2.0','id':2,'method':'tools/list'},
                  {'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'jev_select_resources','arguments':inputs}}]
        run=subprocess.run([sys.executable,'-B',str(MODULE),'serve','--config',str(self.config)],
                           input=''.join(json.dumps(m)+'\n' for m in messages),text=True,capture_output=True,timeout=10)
        self.assertEqual(run.returncode,0,run.stderr)
        rows=[json.loads(line) for line in run.stdout.splitlines()]
        self.assertEqual(rows[0]['result']['serverInfo']['version'],'2.2.0')
        self.assertIn('jev_select_resources',[tool['name'] for tool in rows[1]['result']['tools']])
        result=json.loads(rows[2]['result']['content'][0]['text'])
        self.assertFalse(result['provider_called'])
        self.assertEqual(len(result['selected']),3)
        cli=subprocess.run([sys.executable,'-B',str(MODULE),'select-resources','--config',str(self.config)],
                           input=json.dumps(inputs),text=True,capture_output=True,timeout=10)
        self.assertEqual(cli.returncode,0,cli.stderr)
        self.assertEqual(json.loads(cli.stdout)['selected'],result['selected'])


if __name__=='__main__': unittest.main()
