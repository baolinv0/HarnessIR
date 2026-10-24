"""Read-only contract probe; does not load a model or write repository files."""
from importlib.util import find_spec

from hre.model_aware import build_condition_request, compile_direct_condition, get_model_profile
from hre.models import HREError


asset = dict(asset_id="source_a", role="prediction", path="A.png", sha256="a" * 64,
             pixel_sha256="a" * 64, width=1024, height=768)
config = dict(profile_id="qwen21", strategy="model_aware", compiler="direct")
intent = {"targets": [{"scope": "global", "direction": "reduce blur"}]}

try:
    build_condition_request(config, brief="Restore this photograph.", intent=intent,
                            input_assets=[asset], case_id="audit", source_id="source")
except HREError as exc:
    print("single_image_contract:", str(exc))

for profile_id in ("flux3_klein", "fibo2_dev", "qwen21", "firered11"):
    profile = get_model_profile(profile_id)
    print("profile:", profile_id, "mode=", profile["execution_mode"],
          "compilers=", profile["allowed_compilers"], "status=", profile["capability_status"],
          "validated=", profile["validated_capabilities"])

print("runtime_imports:", {name: find_spec(name) is not None
                           for name in ("torch", "diffusers", "transformers")})

assets = [asset, {**asset, "asset_id": "source_b", "role": "reference", "path": "B.png",
                  "sha256": "b" * 64, "pixel_sha256": "b" * 64}]
native = build_condition_request({**config, "compiler": "native"},
                                 brief="Restore this photograph.", intent=intent,
                                 input_assets=assets, case_id="audit", source_id="source")
try:
    compile_direct_condition(native)
except HREError as exc:
    print("native_is_not_synthesized:", str(exc))
