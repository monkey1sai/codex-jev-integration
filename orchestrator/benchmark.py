"""Phase 4 plan and paired evidence scorer. Does not launch workers or Jev."""
import argparse
import json
import math
from pathlib import Path
from .contracts import ContractError
from .policy import load
from .workspaces import write_new


def score(baseline, experiment):
    def index(rows):
        if type(rows) is not list or not rows:
            raise ContractError('BENCHMARK_SCHEMA')
        result = {}
        fields = {'task_id', 'dag_id', 'contract_hash', 'worker_policy_hash', 'completed',
                  'harmful_assignment', 'tokens', 'wall_seconds', 'retry_count',
                  'escalated', 'merge_conflicts', 'jev_adopted', 'routing_correct', 'hard_policy_bypass'}
        for row in rows:
            if type(row) is not dict or set(row) != fields or row['task_id'] in result:
                raise ContractError('BENCHMARK_SCHEMA')
            for key in ('completed', 'harmful_assignment', 'escalated', 'jev_adopted', 'routing_correct', 'hard_policy_bypass'):
                if type(row[key]) is not bool:
                    raise ContractError('BENCHMARK_SCHEMA')
            for key in ('tokens', 'wall_seconds', 'retry_count', 'merge_conflicts'):
                if type(row[key]) not in (int, float) or not math.isfinite(row[key]) or row[key] < 0:
                    raise ContractError('BENCHMARK_SCHEMA')
            for key in ('tokens', 'retry_count', 'merge_conflicts'):
                if type(row[key]) is not int:
                    raise ContractError('BENCHMARK_SCHEMA')
            result[row['task_id']] = row
        return result
    b, e = index(baseline), index(experiment)
    if b.keys() != e.keys():
        raise ContractError('PAIRED_TASK_SET_MISMATCH')
    for key in b:
        if any(b[key][field] != e[key][field] for field in ('dag_id', 'contract_hash', 'worker_policy_hash')):
            raise ContractError('PAIRED_POLICY_OR_CONTRACT_DRIFT')
    n = len(b)
    def metrics(rows):
        adopted = [r for r in rows if r['jev_adopted']]
        return {'completion_rate': sum(r['completed'] for r in rows) / n,
                'harmful_assignment_rate': sum(r['harmful_assignment'] for r in rows) / n,
                'tokens': sum(r['tokens'] for r in rows),
                'task_wall_seconds_sum': sum(r['wall_seconds'] for r in rows),
                'retry_count': sum(r['retry_count'] for r in rows),
                'escalation_rate': sum(r['escalated'] for r in rows) / n,
                'merge_conflicts': sum(r['merge_conflicts'] for r in rows),
                'adoption_rate': len(adopted) / n,
                'adopted_accuracy': sum(r['routing_correct'] for r in adopted) / len(adopted) if adopted else None,
                'hard_policy_bypasses': sum(r['hard_policy_bypass'] for r in rows)}
    bm, em = metrics(list(b.values())), metrics(list(e.values()))
    relative = 1 - em['harmful_assignment_rate'] / bm['harmful_assignment_rate'] if bm['harmful_assignment_rate'] else None
    return {'status': 'DESCRIPTIVE_ONLY', 'paired_tasks': n, 'dag_clusters': len({r['dag_id'] for r in b.values()}),
            'B': bm, 'E': em, 'harmful_relative_improvement': relative,
            'completion_delta': em['completion_rate'] - bm['completion_rate'],
            'go_no_go': 'NOT_EVALUATED_REQUIRES_CLUSTERED_INFERENCE_AND_INDEPENDENT_LABELS',
            'cost': 'UNKNOWN_WITHOUT_USAGE_PRICING_EVIDENCE', 'elapsed_run_wall_clock': 'REQUIRES_RUN_METADATA'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    plan = sub.add_parser('plan')
    plan.add_argument('--output', required=True)
    evaluate = sub.add_parser('score')
    evaluate.add_argument('--baseline', required=True)
    evaluate.add_argument('--experiment', required=True)
    evaluate.add_argument('--output', required=True)
    args = parser.parse_args()
    if args.command == 'plan':
        result = {'status': 'NOT_STARTED', 'workers_proposed': 20, 'workers_authorized': 2,
                  'arms': ['B', 'E'], 'tasks': {'development': 80, 'heldout': 240, 'stress': 80},
                  'paired_repeats': 3, 'bootstrap_unit': 'DAG', 'live_dispatches': 0,
                  'thresholds': {'harmful_relative_improvement': .20, 'completion_noninferiority': .03,
                                 'jev_adopted_accuracy': .95, 'hard_policy_bypasses': 0},
                  'prerequisites': ['native_isolation', 'trusted_review_import', 'shared_capacity_admission',
                                    'independent_labels', 'explicit_20_worker_capacity_authorization', 'Jev_adapter']}
    else:
        b, _ = load(args.baseline, max_bytes=16777216)
        e, _ = load(args.experiment, max_bytes=16777216)
        result = score(b, e)
    write_new(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
