"""Finite capability routing. Optional advisory is data; never authority."""
from .contracts import ContractError, fingerprint
from .policy import compile_policy, identifier


def route(repo, *, goal, candidate_ids, context, required_ids=(), session=None, advisory=None):
    policy = compile_policy(repo, session=session)
    if not isinstance(goal, str) or not 1 <= len(goal) <= 4000 or type(context) is not dict:
        raise ContractError("ROUTING_CONTEXT")
    if type(candidate_ids) is not list or not 1 <= len(candidate_ids) <= 24 or len(set(candidate_ids)) != len(candidate_ids):
        raise ContractError("CANDIDATE_SET")
    required = list(required_ids)
    if len(set(required)) != len(required) or not set(required) <= set(candidate_ids):
        raise ContractError("REQUIRED_CANDIDATE")
    candidates = []
    for name in candidate_ids:
        identifier(name)
        cap = policy["settings"]["capabilities"].get(name)
        if not cap:
            raise ContractError("UNKNOWN_CAPABILITY")
        candidates.append({"id": name, **cap})
    state_hash = fingerprint({"repo": policy["repo_identity"], "goal": goal,
                              "context": context, "candidates": candidates, "required": required,
                              "policy": policy["policy_hash"]})
    result = {"state_hash": state_hash, "policy_hash": policy["policy_hash"],
              "required_ids": required, "executed": False, "provider_called": False,
              "candidate_ids": candidate_ids, "live_admission": "HELD"}
    if len(candidates) == 1:
        return {**result, "status": "SELECTED", "selected_id": candidate_ids[0], "source": "deterministic"}
    use_jev = policy["settings"]["routing"]["strategy"] == "rules_then_jev" and policy["settings"]["routing"]["jev_enabled"]
    if advisory is not None and not use_jev:
        return {**result, "status": "HELD", "reason": "ADVISORY_ROUTING_DISABLED", "optional_jev": False}
    if not required and advisory is not None:
        if type(advisory) is not dict or set(advisory) != {"state_hash", "selected_id", "observation_id", "advisory_only"}:
            raise ContractError("ADVISORY_SCHEMA")
        if advisory["state_hash"] != state_hash or advisory["advisory_only"] is not True or advisory["selected_id"] not in candidate_ids:
            raise ContractError("STALE_OR_INVALID_ADVISORY")
        # Caller-provided observation is NOT authenticated Jev acceptance.
        return {**result, "status": "PROPOSED", "selected_id": advisory["selected_id"],
                "source": "caller_reported_advisory", "observation_id": advisory["observation_id"],
                "reason": "LOCAL_AVAILABILITY_AND_TRANSMISSION_AUTH_REQUIRED"}
    return {**result, "status": "HELD", "reason": "AMBIGUOUS_ROUTING", "optional_jev": use_jev,
            "routing_request": {"goal": goal, "context": context, "candidates": candidates,
                                "required_ids": required, "state_hash": state_hash} if use_jev else None}
