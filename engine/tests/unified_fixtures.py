"""Explicit synthetic observations for controller validation, never quality data."""
from hre.reference_core.holistic import AXES,PROTECTIONS


def whole_fixture(bindings):
    return dict(image_sha256=bindings,display=dict(method="side_by_side",scale="actual full frames, synthetic fixture",color_basis="test RGB",
        note="Synthetic controller test; no actual quality evaluation"),reviewer=dict(reviewer_id="software_fixture",independence="independent",prior_exposure="Synthetic fixture only"),
        overall_style={axis:dict(reference_status="achieved",relation="closer",direction="fixture direction",magnitude="slight",confidence="high",evidence="Synthetic controller fixture") for axis in AXES},
        preservation={key:dict(status="pass",confidence="high",evidence="Synthetic controller fixture") for key in PROTECTIONS},conflicts=[])
