"""Transport/provenance checks only; no fabricated visual assessment."""
import json
import pytest
from hre.tool_retouch.providers import StructuredProvider,PendingResponse
from hre.tool_retouch.contracts import canonical
from hre.tool_retouch.color import digest_bytes

def test_current_chat_request_and_bound_import(tmp_path):
    config={'mode':'files','provider':'current_chat_offline'}
    with pytest.raises(PendingResponse):
        StructuredProvider(tmp_path,config)('discover_regions',{'user_goal':'protocol test'}, {})
    path=next(tmp_path.glob('*/request.json'));request=json.loads(path.read_text())
    assert request['provider']==request['model']=='current_chat_offline'
    envelope={'request_sha256':digest_bytes(canonical(request).encode()),'observer':'current_chat_offline','payload':{'transport_test_only':True}}
    path.with_name('response.json').write_text(json.dumps(envelope))
    assert StructuredProvider(tmp_path,config)('discover_regions',{'user_goal':'protocol test'}, {})==envelope['payload']
    envelope['observer']='unattributed';path.with_name('response.json').write_text(json.dumps(envelope))
    with pytest.raises(ValueError,match='current chat attribution'):
        StructuredProvider(tmp_path,config)('discover_regions',{'user_goal':'protocol test'}, {})

def test_unknown_provider_rejected_and_legacy_unchanged(tmp_path):
    with pytest.raises(ValueError):StructuredProvider(tmp_path/'bad',{'mode':'files','provider':'fake'})
    with pytest.raises(PendingResponse):StructuredProvider(tmp_path/'legacy',{'mode':'files'})('plan',{}, {})
    request=json.loads(next((tmp_path/'legacy').glob('*/request.json')).read_text())
    assert request['model']=='offline_import' and 'provider' not in request
