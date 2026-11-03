"""The only workflow selector. Historical implementations remain untouched."""
from . import reference_retouch
from .common import require


def select(value):
    version=value.get("workflow_contract")
    if version is None: return None
    if version==reference_retouch.VERSION: return reference_retouch
    if version=="reference_retouch_v2":
        from . import reference_retouch_v2
        return reference_retouch_v2
    require(False,"workflow_contract_invalid","Unknown reference workflow contract")


def enabled(value): return select(value) is not None


def unified(value): return value.get("workflow_contract")=="reference_retouch_v2"


def validate_spec(value):
    implementation=select(value)
    (implementation or reference_retouch).validate_spec(value)


def frozen_contract(intent):
    if intent.get("schema_version")=="hre_reference_intent_v2":
        from .reference_retouch_v2 import frozen_contract as freeze
        return freeze(intent)
    return reference_retouch.frozen_contract(intent)
