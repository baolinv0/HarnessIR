from copy import deepcopy
from pathlib import Path
import re

from hre.models import HREError, file_sha256, now
from hre.storage import case_lock, read_json, write_json

from .contracts import VERSION, digest, require


class Journal:
    def __init__(self, root: Path, limits: dict):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'operations.json'
        self.limits = deepcopy(limits)
        require(all(type(value) is int and value >= 0 for value in limits.values()), 'budget_invalid', 'Call limits must be nonnegative integers')
        with case_lock(self.root):
            if not self.path.exists():
                write_json(self.path, {'schema_version': VERSION, 'limits': self.limits, 'operations': {}})
            ledger = self._load()
            changed = False
            for operation in ledger['operations'].values():
                if operation['state'] == 'submitted':
                    operation.update(state='unknown', error={'code': 'operation_unknown', 'message': 'Submitted operation has no terminal receipt'})
                    changed = True
            if changed:
                write_json(self.path, ledger)

    def _load(self):
        ledger = read_json(self.path)
        require(ledger.get('schema_version') == VERSION and ledger.get('limits') == self.limits,
                'journal_modified', 'Frozen journal limits or version changed')
        require(isinstance(ledger.get('operations'), dict), 'journal_modified', 'Operation registry is missing')
        return ledger

    def snapshot(self):
        with case_lock(self.root):
            return deepcopy(self._load())

    def _operation_directory(self, operation_id):
        require(isinstance(operation_id, str) and operation_id and
                all(re.fullmatch(r'[A-Za-z0-9_.-]+', part) and part not in {'.', '..'} for part in operation_id.split('/')),
                'operation_id_invalid', 'Operation IDs must contain safe nonempty path components')
        return self.root / 'operations' / digest(operation_id)[:24]

    def _replay(self, operation):
        if operation['state'] == 'completed':
            response = self.root / operation['response_path']
            receipt = self.root / operation['receipt_path']
            require(response.resolve().is_relative_to(self.root) and receipt.resolve().is_relative_to(self.root),
                    'journal_modified', 'Saved operation paths escaped the case')
            require(response.is_file() and receipt.is_file() and file_sha256(response) == operation['response_file_sha256'] and
                    file_sha256(receipt) == operation['receipt_file_sha256'], 'operation_modified', 'Completed response or receipt changed')
            return read_json(response)
        if operation['state'] == 'unknown':
            raise HREError('operation_unknown', 'Reconcile ' + operation['operation_id'] + ' before continuing')
        if operation['state'] == 'failed':
            error = operation['error']
            raise HREError(error['code'], error['message'])
        require(operation['state'] == 'prepared', 'operation_state_invalid', 'This operation cannot be submitted')

    def invoke(self, operation_id: str, kind: str, request: dict, callback, *, group: str | None = None):
        directory = self._operation_directory(operation_id)
        if kind.startswith('judge_'):
            require(group in {'J0', 'J1', 'J2'} and kind.startswith('judge_' + group + '_'),
                    'budget_group_invalid', 'Judge operation kind and total-budget group must agree')
        else:
            require(group is None, 'budget_group_invalid', 'Only Judge operations use variant budget groups')
        request_hash = digest(request)
        with case_lock(self.root):
            ledger = self._load()
            existing = ledger['operations'].get(operation_id)
            if existing:
                require(existing['kind'] == kind and existing.get('group') == group and existing['request_sha256'] == request_hash,
                        'request_replay_mismatch', 'An occupied operation identity received a different request')
                saved_request = self.root / existing['request_path']
                require(saved_request.resolve().is_relative_to(self.root) and saved_request.is_file() and
                        file_sha256(saved_request) == existing['request_file_sha256'], 'operation_modified', 'Saved operation request changed')
                if existing['state'] == 'submitted':
                    existing.update(state='unknown', error={'code': 'operation_unknown', 'message': 'Submitted operation has no terminal receipt'})
                    write_json(self.path, ledger)
                result = self._replay(existing)
                if existing['state'] != 'prepared':
                    return result
                operation = existing
            else:
                require(kind in self.limits, 'budget_missing', 'No frozen limit for ' + kind)
                charged = [item for item in ledger['operations'].values() if item['state'] != 'cancelled']
                require(sum(item['kind'] == kind for item in charged) < self.limits[kind], 'budget_exhausted', 'Call limit reached for ' + kind)
                if group:
                    total_key = 'judge_' + group + '_total'
                    require(total_key in self.limits, 'budget_missing', 'No frozen total limit for ' + group)
                    require(sum(item.get('group') == group for item in charged) < self.limits[total_key], 'budget_exhausted', 'Total Judge call limit reached')
                directory.mkdir(parents=True, exist_ok=True)
                request_path = directory / 'request.json'
                write_json(request_path, request)
                operation = {'operation_id': operation_id, 'kind': kind, 'group': group,
                             'request_sha256': request_hash, 'request_path': request_path.relative_to(self.root).as_posix(),
                             'request_file_sha256': file_sha256(request_path), 'state': 'prepared', 'created_at': now(),
                             'execution_manifest_sha256': request.get('execution_manifest_sha256'), 'cost_status': 'unknown',
                             'resolutions': []}
                ledger['operations'][operation_id] = operation
                write_json(self.path, ledger)
            request_path = self.root / operation['request_path']
            require(request_path.is_file() and file_sha256(request_path) == operation['request_file_sha256'] and
                    digest(read_json(request_path)) == request_hash, 'operation_modified', 'Prepared request changed')
            operation.update(state='submitted', submitted_at=now())
            write_json(self.path, ledger)
            try:
                response = callback()
            except Exception as exc:
                uncertain = (isinstance(exc, (TimeoutError, ConnectionError)) or
                             any(word in type(exc).__name__.lower() for word in ('timeout', 'connection', 'urlerror')) or
                             getattr(exc, 'code', '') in {'operation_unknown', 'worker_submission_unknown', 'worker_protocol_error', 'worker_response_mismatch', 'worker_exited'})
                operation.update(state='unknown' if uncertain else 'failed', ended_at=now(),
                                 error={'code': 'operation_unknown' if uncertain else getattr(exc, 'code', 'operation_failed'),
                                        'message': 'External operation did not return a reliable response' if uncertain else str(exc)})
                write_json(self.path, ledger)
                if uncertain:
                    raise HREError('operation_unknown', 'Reconcile ' + operation_id + ' before continuing') from exc
                raise HREError(operation['error']['code'], operation['error']['message']) from exc
            require(isinstance(response, dict), 'operation_response_invalid', 'Operation response must be a JSON object')
            response_path = directory / 'response.json'
            receipt_path = directory / 'receipt.json'
            write_json(response_path, response)
            receipt = {'operation_id': operation_id, 'request_sha256': request_hash,
                       'response_sha256': digest(response), 'execution_manifest_sha256': operation['execution_manifest_sha256'],
                       'completed_at': now(), 'cost_status': 'unknown'}
            write_json(receipt_path, receipt)
            operation.update(state='completed', response_path=response_path.relative_to(self.root).as_posix(),
                             receipt_path=receipt_path.relative_to(self.root).as_posix(),
                             response_file_sha256=file_sha256(response_path), receipt_file_sha256=file_sha256(receipt_path), ended_at=now())
            write_json(self.path, ledger)
            return deepcopy(response)

    def _reconciliation_path(self, relative):
        require(isinstance(relative, str) and relative, 'reconcile_evidence_invalid', 'Evidence path is required')
        path = (self.root / relative).resolve()
        require(path.is_relative_to((self.root / 'reconciliation').resolve()) and path.is_file(),
                'reconcile_evidence_invalid', 'Import reconciliation evidence below case/reconciliation first')
        return path

    def reconcile(self, operation_id: str, resolution: dict):
        required = {'schema_version', 'record_type', 'operation_id', 'request_sha256', 'decision', 'operator', 'reason', 'evidence_refs'}
        require(required <= resolution.keys() and resolution['schema_version'] == VERSION and resolution['record_type'] == 'reconciliation',
                'reconcile_invalid', 'Incomplete reconciliation record')
        require(resolution['operation_id'] == operation_id and resolution['operator'] and resolution['reason'],
                'reconcile_invalid', 'Operation and operator identity are required')
        decision = resolution['decision']
        require(decision in {'confirmed_completed', 'confirmed_not_executed', 'still_unknown'}, 'reconcile_invalid', 'Unknown resolution decision')
        resolution_hash = digest(resolution)
        with case_lock(self.root):
            ledger = self._load()
            require(operation_id in ledger['operations'], 'operation_missing', operation_id)
            operation = ledger['operations'][operation_id]
            require(operation['request_sha256'] == resolution['request_sha256'], 'reconcile_binding_mismatch', 'Resolution belongs to another request')
            if resolution_hash in operation.get('resolutions', []):
                return deepcopy(operation)
            require(operation['state'] == 'unknown', 'reconcile_state_invalid', 'Only unknown operations accept new resolutions')
            evidence_paths = [self._reconciliation_path(path) for path in resolution['evidence_refs']]
            if decision == 'confirmed_completed':
                response_path = self._reconciliation_path(resolution.get('response_path'))
                receipt_path = self._reconciliation_path(resolution.get('receipt_path'))
                response, receipt = read_json(response_path), read_json(receipt_path)
                require(receipt.get('operation_id') == operation_id and receipt.get('request_sha256') == operation['request_sha256'] and
                        receipt.get('response_sha256') == digest(response), 'reconcile_binding_mismatch', 'Receipt does not bind this response and request')
                if operation.get('execution_manifest_sha256'):
                    require(receipt.get('execution_manifest_sha256') == operation['execution_manifest_sha256'],
                            'reconcile_binding_mismatch', 'Receipt belongs to another execution manifest')
                operation.update(state='completed', response_path=response_path.relative_to(self.root).as_posix(),
                                 receipt_path=receipt_path.relative_to(self.root).as_posix(), response_file_sha256=file_sha256(response_path),
                                 receipt_file_sha256=file_sha256(receipt_path), cost_status=receipt.get('cost_status', 'unknown'))
            elif decision == 'confirmed_not_executed':
                require(evidence_paths, 'reconcile_evidence_invalid', 'Provider or worker nonexecution proof is required')
                proof = [read_json(path) for path in evidence_paths if path.suffix == '.json']
                require(any(item.get('operation_id') == operation_id and item.get('request_sha256') == operation['request_sha256'] and
                            item.get('not_executed') is True for item in proof), 'reconcile_binding_mismatch', 'No request-bound nonexecution proof')
                operation.update(state='failed', error={'code': 'confirmed_not_executed', 'message': 'Operator imported request-bound nonexecution proof'}, cost_status='not_incurred')
            directory = self._operation_directory(operation_id)
            write_json(directory / ('resolution_' + resolution_hash[:16] + '.json'), resolution)
            operation.setdefault('resolutions', []).append(resolution_hash)
            operation['reconciled_at'] = now()
            write_json(self.path, ledger)
            return deepcopy(operation)
