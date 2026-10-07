"""Versioned selection metadata; reuse the existing locked, no-follow journal IO."""
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import uuid

_spec = importlib.util.spec_from_file_location('selection_journal_io', Path(__file__).with_name('observability.py'))
j = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(j)

STEM = 'resource-decisions'
BASE = {'kind', 'observation_id', 'workspace_id', 'schema_version', 'policy_version',
        'question_version', 'recorded_at', 'elapsed_ms'}
DECISION = BASE | {'mode', 'reason', 'context_status', 'selected', 'suggested_route',
                   'provider_called', 'provider_model', 'usage', 'inventory_version'}
OUTCOME = BASE | {'adopted', 'result', 'tool_calls', 'rework_count', 'reported_model',
                 'provenance', 'execution_verified', 'advisory_only'}
REASONS = {'DETERMINISTIC_REVIEW_GATE', 'LOCAL_VERIFICATION_REQUIRED', 'JEV_DISABLED',
           'INSUFFICIENT_CONTEXT', 'STALE_INVENTORY', 'REQUIRED_RESOURCE_UNAVAILABLE',
           'RESOURCE_DEPENDENCY_OR_CONFLICT', 'REQUIRED_RESOURCES', 'NO_ELIGIBLE_CANDIDATES',
           'COMBINED_SELECTION', 'LOW_CONFIDENCE', 'API_ERROR', 'CONFIG_ERROR'}


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _hash(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _valid(row):
    if type(row) is not dict or row.get('kind') not in ('decision', 'outcome'):
        return False
    if set(row) != (DECISION if row['kind'] == 'decision' else OUTCOME):
        return False
    if not j._valid_id(row['observation_id']) or not _hash(row['workspace_id']):
        return False
    if any(type(row[k]) is not int or row[k] != v for k, v in
           [('schema_version', 2), ('policy_version', 1), ('question_version', 1)]):
        return False
    if type(row['recorded_at']) is not str or not re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z', row['recorded_at']):
        return False
    if row['elapsed_ms'] is not None and not j.bounded_int(row['elapsed_ms']):
        return False
    if row['kind'] == 'outcome':
        return ((row['adopted'] is None or type(row['adopted']) is bool) and
                type(row['result']) is str and row['result'] in {'completed', 'failed', 'cancelled', 'unknown'} and
                all(row[k] is None or j.bounded_int(row[k]) for k in ('tool_calls', 'rework_count')) and
                type(row['reported_model']) is str and row['reported_model'] in j.MODELS | {'unknown'} and
                row['provenance'] == 'caller_reported' and row['execution_verified'] is False and row['advisory_only'] is True)
    if (type(row['mode']) is not str or row['mode'] not in {'combined', 'resources'} or
            type(row['reason']) is not str or row['reason'] not in REASONS or
            type(row['context_status']) is not str or row['context_status'] not in {'not_evaluated', 'sufficient', 'insufficient', 'uncertain'} or
            (row['suggested_route'] is not None and (type(row['suggested_route']) is not str or row['suggested_route'] not in j.ROUTES)) or
            (row['provider_called'] is not None and type(row['provider_called']) is not bool) or
            (row['provider_model'] is not None and (type(row['provider_model']) is not str or not re.fullmatch(r'jev-[a-zA-Z0-9._-]{1,48}', row['provider_model']))) or
            (row['inventory_version'] is not None and not _hash(row['inventory_version']))):
        return False
    usage = row['usage']
    if type(usage) is not dict or set(usage) != {'input_tokens', 'output_tokens'} or not all(v is None or j.bounded_int(v) for v in usage.values()):
        return False
    selected = row['selected']
    return (type(selected) is list and len(selected) <= 24 and
            all(type(v) is dict and set(v) == {'id_hash', 'kind', 'source'} and _hash(v['id_hash']) and
                type(v['kind']) is str and v['kind'] in {'tool', 'mcp', 'skill'} and
                type(v['source']) is str and v['source'] in {'required', 'jev_choice'} for v in selected))


def _options(path, workspace):
    opts = j.configuration(path, workspace)
    if opts['status'] == 'ready':
        # Separate bounded file; the original journal and its capacity remain intact.
        opts = {**opts, 'max_records': min(opts['max_records'], 250),
                'max_bytes': min(opts['max_bytes'], 524288)}
    return opts


def _base(kind, workspace, oid, elapsed):
    return {'kind': kind, 'observation_id': oid, 'workspace_id': j.workspace_id(workspace),
            'schema_version': 2, 'policy_version': 1, 'question_version': 1,
            'recorded_at': j._timestamp(), 'elapsed_ms': elapsed}


def observe(path, args, result, elapsed):
    opts = _options(path, args['workspace'])
    if opts['status'] != 'ready':
        return {'status': opts['status']}
    try:
        oid = str(uuid.uuid4())
        reason = result['reason']
        if reason not in REASONS:
            reason = 'API_ERROR' if result.get('provider_attempted') else 'CONFIG_ERROR'
        row = {**_base('decision', args['workspace'], oid, elapsed),
               'mode': 'combined' if args.get('select_role', True) else 'resources',
               'reason': reason, 'context_status': result.get('context_status', 'not_evaluated'),
               'selected': [{'id_hash': digest(x['id']), 'kind': x['kind'], 'source': x['source']}
                            for x in result.get('selected', [])],
               'suggested_route': result.get('route'), 'provider_called': result.get('provider_called'),
               'provider_model': result.get('provider_model'),
               'usage': result.get('usage', {'input_tokens': None, 'output_tokens': None}),
               'inventory_version': args.get('inventory', {}).get('version')}
        with j._locked(path, True, STEM) as journal:
            rows, size = j._read(journal, opts, _valid)
            j._append(journal, row, rows, size, opts, _valid)
        return {'status': 'written', 'id': oid, 'schema_version': 2}
    except j.JournalFailure as error:
        return {'status': str(error)}
    except Exception:
        return {'status': 'io_error'}


def report(path, args):
    allowed = {'workspace', 'observation_id', 'adopted', 'result', 'elapsed_ms', 'tool_calls', 'rework_count', 'reported_model'}
    if type(args) is not dict or set(args) - allowed or not {'workspace', 'observation_id'} <= set(args):
        raise j.JournalFailure('INVALID_OUTCOME_ARGUMENTS')
    if type(args['workspace']) is not str or not j._valid_id(args['observation_id']):
        raise j.JournalFailure('INVALID_OUTCOME_ARGUMENTS')
    row = {**_base('outcome', args['workspace'], args['observation_id'], args.get('elapsed_ms')),
           'adopted': args.get('adopted'), 'result': args.get('result', 'unknown'),
           'tool_calls': args.get('tool_calls'), 'rework_count': args.get('rework_count'),
           'reported_model': args.get('reported_model', 'unknown'),
           'provenance': 'caller_reported', 'execution_verified': False, 'advisory_only': True}
    if not _valid(row):
        raise j.JournalFailure('INVALID_OUTCOME_ARGUMENTS')
    opts = _options(path, args['workspace'])
    if opts['status'] != 'ready':
        return {'status': opts['status'], 'provenance': 'caller_reported', 'execution_verified': False}
    with j._locked(path, True, STEM) as journal:
        rows, size = j._read(journal, opts, _valid)
        related = [r for r in rows if r['workspace_id'] == row['workspace_id'] and r['observation_id'] == row['observation_id']]
        if not any(r['kind'] == 'decision' for r in related):
            raise j.JournalFailure('OBSERVATION_NOT_FOUND')
        old = next((r for r in related if r['kind'] == 'outcome'), None)
        if old:
            if {k: v for k, v in old.items() if k != 'recorded_at'} != {k: v for k, v in row.items() if k != 'recorded_at'}:
                raise j.JournalFailure('OUTCOME_CONFLICT')
            status = 'duplicate'
        else:
            j._append(journal, row, rows, size, opts, _valid)
            status = 'written'
    return {'status': status, 'id': row['observation_id'], 'provenance': 'caller_reported',
            'execution_verified': False, 'advisory_only': True}
