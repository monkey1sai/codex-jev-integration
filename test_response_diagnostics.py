"""Offline failure taxonomy, call-path propagation, and privacy regression guards."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from datetime import datetime, timezone

spec = importlib.util.spec_from_file_location('diagnostic_candidate', Path(__file__).parent/'payload/jev/decision.py')
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


def wire(body):
    return {'model':'jev-test','answers':{
        k:{'type':'choice','choice':next(iter(q['criteria'])),'confidence':1,
           'probabilities':{i:int(i==next(iter(q['criteria']))) for i in q['criteria']}}
        for k,q in body['questions'].items()},'usage':{'input_tokens':10,'output_tokens':2}}


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.config=self.root/'config.json'
        self.config.write_text(json.dumps({'enabled':True,'confidence_threshold':.8,'timeout_seconds':20,
            'observability':{'enabled':True,'max_records':100,'max_bytes':524288}}))
        self.questions={'skill':{'criteria':{'read':'Read','none':'No skill'}}}
        self.base=wire({'questions':self.questions})

    def test_failure_taxonomy_rejects_without_payload_echo(self):
        cases=[
            ('RESPONSE_SHAPE',lambda w:w.pop('answers')),
            ('MODEL_ID',lambda w:w.update(model='PRIVATE_PROVIDER_SECRET')),
            ('QUESTION_SET',lambda w:w['answers'].update(extra={})),
            ('ANSWER_SHAPE',lambda w:w['answers']['skill'].pop('confidence')),
            ('ANSWER_TYPE',lambda w:w['answers']['skill'].update(type='noul')),
            ('CHOICE_OPTION',lambda w:w['answers']['skill'].update(choice=['PRIVATE_PROVIDER_SECRET'])),
            ('PROBABILITY_KEYS',lambda w:w['answers']['skill']['probabilities'].pop('none')),
            ('CONFIDENCE_VALUE',lambda w:w['answers']['skill'].update(confidence=True)),
            ('CONFIDENCE_VALUE',lambda w:w['answers']['skill'].update(confidence=float('nan'))),
            ('PROBABILITY_VALUE',lambda w:w['answers']['skill']['probabilities'].update(none=-.01)),
            ('PROBABILITY_VALUE',lambda w:w['answers']['skill']['probabilities'].update(none=False)),
            ('PROBABILITY_SUM',lambda w:w['answers']['skill']['probabilities'].update(none=.01)),
            ('CHOICE_ARGMAX',lambda w:w['answers']['skill'].update(choice='none')),
        ]
        for code,mutate in cases:
            with self.subTest(code=code):
                value=copy.deepcopy(self.base);mutate(value)
                with self.assertRaises(d.SafeFailure) as raised:
                    d.validate_resource_answers(value,self.questions)
                self.assertEqual(str(raised.exception),'INVALID_RESOURCE_RESPONSE')
                self.assertEqual(raised.exception.validation_code,code)
                self.assertNotIn('PRIVATE_PROVIDER_SECRET',str(raised.exception))

    def test_valid_ties_rounding_and_usage_behavior_preserved(self):
        value=copy.deepcopy(self.base)
        value['answers']['skill'].update(confidence=.5,probabilities={'read':.5,'none':.5})
        value['usage']={'input_tokens':True,'output_tokens':2}
        model,answers,usage=d.validate_resource_answers(value,self.questions)
        self.assertEqual(model,'jev-test')
        self.assertEqual(answers['skill']['choice'],'read')
        self.assertEqual(usage,{'input_tokens':None,'output_tokens':None})
        value['answers']['skill']['probabilities']={'read':.50025,'none':.5}
        d.validate_resource_answers(value,self.questions)  # Existing .001 tolerance unchanged.

    def test_resource_call_keeps_required_and_exposes_only_fixed_code(self):
        args={'workspace':str(self.root),'task_summary':'Synthetic choice',
            'required_ids':['mandatory'],'candidates':[
                {'id':'mandatory','kind':'skill','description':'Required','available':True,'in_scope':True},
                {'id':'read','kind':'tool','description':'Read','available':True,'in_scope':True}]}
        calls=[]
        def fake(body,config):
            calls.append(1);value=wire(body)
            value['answers']['tool']['probabilities'].pop('none')
            value['private']='PRIVATE_PROVIDER_SECRET'
            return value
        result=d.select_resources(args,self.config,fake)
        self.assertEqual(calls,[1])
        self.assertEqual(result['validation_code'],'PROBABILITY_KEYS')
        self.assertEqual(result['reason'],'INVALID_RESOURCE_RESPONSE')
        self.assertEqual([r['id'] for r in result['selected']],['mandatory'])
        self.assertIsNone(result['provider_called'])
        self.assertFalse(result['executed'])
        self.assertNotIn('PRIVATE_PROVIDER_SECRET',json.dumps(result))

    def test_combined_call_reports_code_without_changing_journal_schema(self):
        args={'workspace':str(self.root),'task_summary':'Synthetic decision','stage':'work',
            'context':{'goal':'Select a reader','success_criteria':['One reader'],
                'environment':['Synthetic'],'evidence':['Reader capability'],
                'constraints':[],'unknowns':[],'critical_unknowns':[]},
            'inventory':{'captured_at':datetime.now(timezone.utc).isoformat(),'version':'a'*64},
            'candidates':[{'id':'read','kind':'tool','description':'Read','when_to_use':'Read sources',
                'available':True,'in_scope':True,'limits':[],'requires':[],'conflicts':[]}]}
        calls=[]
        def fake(body,config):
            calls.append(1);value=wire(body)
            value['answers']['tool']['probabilities']['none']=.01
            return value
        result=d.decide(args,self.config,fake)
        self.assertEqual(calls,[1])
        self.assertEqual(result['validation_code'],'PROBABILITY_SUM')
        self.assertEqual(result['reason'],'INVALID_RESOURCE_RESPONSE')
        self.assertEqual(result['selected'],[])
        self.assertTrue(result['advisory_only'])
        self.assertEqual(result['observation']['status'],'written')
        records=list((self.root/'audit').glob('*.jsonl'))
        self.assertEqual(len(records),1)
        rows=[json.loads(line) for line in records[0].read_text().splitlines()]
        self.assertNotIn('validation_code',rows[0])


if __name__=='__main__':
    unittest.main()
