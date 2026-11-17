import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
from hre.candidates.cli import make_fixture


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Create a synthetic CPU-only candidate workflow case')
    parser.add_argument('--out', type=Path, required=True)
    print(json.dumps(make_fixture(parser.parse_args().out), ensure_ascii=False))
