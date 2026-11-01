"""Private posthoc policy storage; never imported by diagnosis or execution.

No acceptance decision is implemented in S0/S1. Only an explicit verifier/selector
consumer may use read_policy_for_verifier; exports never enumerate this directory.
"""
from pathlib import Path
import os

from hre.paths import safe_path
from hre.storage import case_lock, read_json, write_json
from .contracts import exact, identifier, require, record, validate_record


def _validate_policy(policy):
    exact(policy, ('policy_id', 'version', 'overall_style_achieved_required',
                   'posthoc_principles', 'unknown_or_major_deviation'))
    identifier(policy['policy_id'])
    identifier(policy['version'])
    require(policy['overall_style_achieved_required'] is True, 'overall B style prerequisite cannot be disabled')
    require(isinstance(policy['posthoc_principles'], list) and policy['posthoc_principles']
            and all(isinstance(p, str) and p.strip() for p in policy['posthoc_principles']), 'posthoc principles required')
    require(policy['unknown_or_major_deviation'] == 'insufficient_evidence_or_reject', 'major or unknown deviations cannot be automatically minor')


def store_policy(root, policy):
    _validate_policy(policy)
    state = validate_record(read_json(safe_path(root, 'state.json', True)))
    with case_lock(Path(root)):
        directory = safe_path(root, 'private_verification')
        directory.mkdir(exist_ok=True, mode=0o700)
        target = safe_path(root, 'private_verification/' + policy['policy_id'] + '.json')
        require(not target.exists(), 'policy ID frozen; create a new policy ID for revisions')
        value = record(state['sample_id'], 'acceptance_policy', policy)
        write_json(target, value)
        os.chmod(target, 0o600)
        return value


def read_policy_for_verifier(root, policy_id):
    identifier(policy_id)
    value = validate_record(read_json(safe_path(root, 'private_verification/' + policy_id + '.json', True)))
    require(value['kind'] == 'acceptance_policy', 'wrong private record kind')
    _validate_policy(value['payload'])
    state = validate_record(read_json(safe_path(root, 'state.json', True)))
    require(value['sample_id'] == state['sample_id'], 'policy/sample mismatch')
    return value
