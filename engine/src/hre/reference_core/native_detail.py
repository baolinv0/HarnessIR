"""Independent native-file observations, bound to exact result/evaluation bytes.

These are explicit review attestations. Neither image dimensions nor a display
preview is evidence that authentic source detail survived an edit.
"""
from copy import deepcopy
import re
from hre.models import canonical_json
from .contracts import size

BINDINGS=("source_sha256","native_sha256","native_size","result_hash","evaluation_hash","selected_sha256")
KEYS=("schema_version","review_id",*BINDINGS,"reviewer","display","status","confidence","observation")


def _check(ok,message):
    if not ok:raise ValueError(message)


def _text(value):return isinstance(value,str) and 0<len(value.strip())<=20000


def validate_detail(spec,expected):
    _check(isinstance(spec,dict) and set(spec)==set(KEYS),"Complete versioned native-detail observation required")
    _check(spec["schema_version"]=="hre_native_detail_review_v1","Unknown native-detail review version")
    _check(isinstance(spec["review_id"],str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}",spec["review_id"]),"Invalid native-detail review identity")
    for key in BINDINGS:
        if key=="native_size":size(spec[key],"native_size")
        else:_check(isinstance(spec[key],str) and re.fullmatch(r"[a-f0-9]{64}",spec[key]),"Invalid native-detail hash")
        _check(key in expected and spec[key]==expected[key],"Native-detail observation has a stale/wrong "+key)
    reviewer=spec["reviewer"];display=spec["display"]
    _check(isinstance(reviewer,dict) and set(reviewer)=={"reviewer_id","independence","prior_exposure"},"Disclose native-detail reviewer and exposure")
    _check(_text(reviewer["reviewer_id"]) and reviewer["independence"] in {"independent","same_model","unknown"} and _text(reviewer["prior_exposure"]),"Invalid native-detail reviewer")
    _check(isinstance(display,dict) and set(display)=={"method","note"} and display["method"] in {"native_pixels_1_to_1","native_zoom"} and _text(display["note"]),"Review actual native pixels, not an enlarged delivery preview")
    _check(spec["status"] in {"pass","fail","uncertain","unknown"} and spec["confidence"] in {"high","medium","low","unknown"} and _text(spec["observation"]),"Actual detail state, confidence and observation required")
    canonical_json(spec)
    return deepcopy(spec)


def detail_status(spec):
    if spec is None:return "uncertain"
    if spec["reviewer"]["independence"]!="independent" or spec["confidence"]!="high":return "uncertain"
    return spec["status"] if spec["status"] in {"pass","fail"} else "uncertain"


def decision_fields(spec):
    if spec is None:return None
    return {**{key:deepcopy(spec[key]) for key in BINDINGS},"status":spec["status"],"confidence":spec["confidence"],
        "independence":spec["reviewer"]["independence"],"viewing_method":spec["display"]["method"]}
