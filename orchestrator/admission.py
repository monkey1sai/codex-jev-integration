"""Diagnostic receipts, never an execution or review authorization.

Codex 0.160.1/0.161.0 thread metadata is configured model/effort, not
per-turn telemetry. Hashes and a signature cannot change that distinction.
"""
from .contracts import ContractError, fingerprint


def app_server_review_metadata(target, started, completed):
    """Retain only non-secret metadata; caller-supplied objects are untrusted.

    This function deliberately has no observed-model input. No transport
    attester is enrolled yet, so even correctly shaped metadata cannot PASS.
    Assistant items/stdout are never used to infer identity or model.
    """
    if type(started) is not dict or type(completed) is not dict:
        raise ContractError('REVIEW_RUNTIME_SCHEMA')
    thread, turn = started.get('thread'), completed.get('turn')
    if (type(thread) is not dict or type(turn) is not dict
            or not isinstance(thread.get('id'), str) or not thread['id']
            or not isinstance(thread.get('sessionId'), str) or not thread['sessionId']
            or not isinstance(turn.get('id'), str) or not turn['id']):
        raise ContractError('REVIEW_RUNTIME_SCHEMA')
    if completed.get('threadId') != thread['id']:
        raise ContractError('REVIEW_RUNTIME_SESSION_MISMATCH')
    if turn.get('status') != 'completed' or turn.get('error') is not None:
        raise ContractError('REVIEW_RUNTIME_NOT_COMPLETED')
    model, effort = started.get('model'), started.get('reasoningEffort')
    if not isinstance(model, str) or not model or not isinstance(effort, str) or not effort:
        raise ContractError('REVIEW_RUNTIME_CONFIG_MISSING')
    # A bounded, allowlisted receipt; never persist raw provider/session output.
    if any(len(v) > 256 for v in (thread['id'], thread['sessionId'], turn['id'], model, effort)):
        raise ContractError('REVIEW_RUNTIME_SIZE')
    return {'schema_version': 1, 'purpose': 'codex-orchestrator/review-runtime-diagnostic/v1',
            'target_hash': fingerprint(target), 'queue_id': target['queue_id'],
            'task_id': target['task_id'], 'attempt_id': target['attempt_id'], 'epoch': target['epoch'],
            'policy_hash': target['policy_hash'], 'artifact_hash': target['artifact_hash'],
            'receipt_hash': target['receipt_hash'], 'nonce': target['nonce'],
            'thread_id': thread['id'], 'session_id': thread['sessionId'], 'turn_id': turn['id'],
            'configured_model': model, 'configured_effort': effort, 'turn_status': 'completed',
            'observed_model': None, 'observed_effort': None,
            'source': 'UNVERIFIED_CALLER_SUPPLIED_APP_SERVER_METADATA',
            'admission': 'BLOCKED', 'blockers': ['UNTRUSTED_RUNTIME_SOURCE',
              'MISSING_OBSERVED_MODEL', 'MISSING_EFFECTIVE_EFFORT',
              'REVIEWER_IDENTITY_UNVERIFIED', 'NATIVE_CONTAINMENT_UNVERIFIED']}
