"""Global core operator CLI. Contains no live worker/provider execution command."""
import argparse
import json
from pathlib import Path
from .contracts import ContractError
from .policy import compile_policy, load
from .provision import plan, apply, recover, write_new
from .tasks import validate_tasks
from .core_queue import CoreQueue
from .phase2 import Phase2Queue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    effective = sub.add_parser("effective")
    effective.add_argument("--repo", required=True)
    effective.add_argument('--session', help='Explicit custom-controller JSON overlay; not Codex native config')
    check = sub.add_parser("check-tasks")
    check.add_argument("--repo", required=True)
    check.add_argument("--tasks", required=True)
    setup = sub.add_parser("plan-repo")
    setup.add_argument("--repo", required=True)
    setup.add_argument("--spec", required=True)
    setup.add_argument("--output", required=True)
    install = sub.add_parser("apply-repo")
    install.add_argument("--repo", required=True)
    install.add_argument("--plan", required=True)
    install.add_argument("--sha256", required=True)
    install.add_argument("--journal", required=True)
    recovery = sub.add_parser("rollback-repo")
    recovery.add_argument("--repo", required=True)
    recovery.add_argument("--journal", required=True)
    recovery.add_argument("--sha256", required=True)
    queue = sub.add_parser("enqueue")
    queue.add_argument("--repo", required=True)
    queue.add_argument("--tasks", required=True)
    queue.add_argument("--database", required=True)
    for name in ('phase2-enqueue', 'phase2-status', 'phase2-expire', 'phase2-review-challenge',
                 'phase2-import-review', 'phase2-supervise-mock', 'phase2-merge-check'):
        command = sub.add_parser(name)
        command.add_argument('--repo', required=True)
        command.add_argument('--database', required=True)
        command.add_argument('--session')
        command.add_argument('--evidence-mode', choices=['production', 'OFFLINE_TEST'], default='production')
        command.add_argument('--review-registry')
        command.add_argument('--registry-sha256')
        if name == 'phase2-enqueue':
            command.add_argument('--tasks', required=True)
        if name in {'phase2-review-challenge', 'phase2-merge-check'}:
            command.add_argument('--task-id', required=True)
        if name == 'phase2-import-review':
            command.add_argument('--envelope', required=True)
        if name == 'phase2-supervise-mock':
            command.add_argument('--run-root', required=True)
            command.add_argument('--max-active', type=int, default=1)
            command.add_argument('--max-seconds', type=float, default=30)
            command.add_argument('--validator-registry')
            command.add_argument('--validator-sha256')
        if name == 'phase2-merge-check':
            command.add_argument('--integration-repo', required=True)
            command.add_argument('--integration-head', required=True)
            command.add_argument('--candidate-head', required=True)
    args = parser.parse_args()
    try:
        if args.command == "effective":
            session = load(args.session)[0] if args.session else None
            result = compile_policy(args.repo, session=session)
        elif args.command.startswith('phase2-'):
            session = load(args.session)[0] if args.session else None
            ledger = Phase2Queue(args.database, args.repo, session=session, evidence_mode=args.evidence_mode,
                                  review_registry=args.review_registry, registry_sha256=args.registry_sha256)
            evidence = None
            if args.command == 'phase2-enqueue':
                tasks, _ = load(args.tasks, max_bytes=16777216)
                ledger.enqueue(tasks)
            elif args.command == 'phase2-expire':
                ledger.expired()  # fence only; never infer process-tree cleanup
            elif args.command == 'phase2-review-challenge':
                evidence = ledger.review_challenge(args.task_id)
            elif args.command == 'phase2-import-review':
                envelope, _ = load(args.envelope)
                evidence = ledger.import_review(envelope)
            elif args.command == 'phase2-supervise-mock':
                from .supervisor import Supervisor
                from .validators import ValidatorRegistry
                if bool(args.validator_registry) != bool(args.validator_sha256):
                    raise ContractError('VALIDATOR_TRUST_PIN')
                validators = ValidatorRegistry(ledger, args.validator_registry, args.validator_sha256) if args.validator_registry else None
                supervisor = Supervisor(ledger, Path(args.run_root), Path(args.repo),
                                        max_active=args.max_active, validators=validators)
                evidence = supervisor.run(max_seconds=args.max_seconds)
            elif args.command == 'phase2-merge-check':
                from .merge_validation import validate_queue_merge
                evidence = validate_queue_merge(ledger, args.task_id, args.integration_repo,
                                                args.integration_head, args.candidate_head)
            result = {'queue': ledger.snapshot(), 'merge_queue': ledger.merge_snapshot(), 'evidence': evidence,
                      'native_dispatches': 0, 'merge_executed': False}
            if args.command in {'phase2-enqueue', 'phase2-status', 'phase2-expire'}:
                result['executed'] = False  # Preserve the existing operator response contract.
        elif args.command == "check-tasks":
            tasks, _ = load(args.tasks, max_bytes=16777216)
            validate_tasks(tasks, compile_policy(args.repo))
            result = {"status": "VALID", "tasks": len(tasks), "executed": False}
        elif args.command == "plan-repo":
            spec, _ = load(args.spec)
            result = {"status": "PLANNED", "sha256": write_new(args.output, plan(args.repo, spec)), "plan": args.output}
        elif args.command == "apply-repo":
            result = apply(args.repo, args.plan, args.sha256, args.journal)
        elif args.command == "rollback-repo":
            result = recover(args.repo, args.journal, args.sha256)
        else:
            database = Path(args.database).absolute()
            if database.resolve().is_relative_to(Path(args.repo).resolve()):
                raise ContractError("CONTROLLER_DATABASE_OUTSIDE_REPO_REQUIRED")
            tasks, _ = load(args.tasks, max_bytes=16777216)
            ledger = CoreQueue(database, args.repo)
            ledger.enqueue(tasks)
            result = {"status": "QUEUED", "count": len(ledger.snapshot()["tasks"]), "executed": False}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ContractError, OSError, TypeError) as error:
        code = str(error) if isinstance(error, ContractError) else "CONFIG_OR_FILESYSTEM_ERROR"
        print(json.dumps({"status": "HELD", "reason": code}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
