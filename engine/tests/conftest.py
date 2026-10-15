import json
import uuid
from pathlib import Path

import pytest
from PIL import Image

DESIGN = Path(__file__).resolve().parents[2] / "Design_v1_20261012"


def pytest_configure(config):
    if config.option.basetemp is None:
        directory = Path(__file__).resolve().parents[1] / ".test-runs"
        directory.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(directory / uuid.uuid4().hex)


@pytest.fixture
def photo(tmp_path):
    path = tmp_path / "source.png"
    Image.new("RGB", (64, 48), (30, 50, 70)).save(path)
    return path


@pytest.fixture
def fixture_json():
    def read(name):
        return json.loads((DESIGN / "examples" / f"{name}.json").read_text(encoding="utf-8"))
    return read
