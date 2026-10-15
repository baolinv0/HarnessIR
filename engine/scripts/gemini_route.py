"""Opt-in Gemini API route; one role request at a time, no browser automation."""
import argparse
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'engine/src'))
from hir_manual.gemini_api import configuration, list_models, run_task
from hir_manual.service import Controller

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['models', 'new', 'run'])
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--key-file', type=Path)
    parser.add_argument('--key-env', default='GEMINI_API_KEY')
    parser.add_argument('--retry-text-after-timeout', action='store_true', help='One explicit audited text-role retry, never image regeneration')
    parser.add_argument('--case'); parser.add_argument('--input', type=Path)
    parser.add_argument('--intent', default='Restore conservatively; preserve scene, identity, text, natural texture and lighting. Do not invent details.')
    parser.add_argument('--image-model'); parser.add_argument('--text-model')
    parser.add_argument('--evidence-profile', default='cpu_probe_v1')
    parser.add_argument('--media-transport', choices=['files_api_v1'], default=None,
                        help='Explicit original-byte Files API upload; default remains inline')
    args = parser.parse_args()
    try:
        if args.action == 'models':
            result = list_models(args.key_file, args.key_env)
        elif args.action == 'new':
            cfg = configuration(args.image_model, args.text_model, media_transport=args.media_transport)
            cfg.update(evidence_profile_id=args.evidence_profile, auto_local_tools=False, max_generations=3)
            result = Controller(args.root).new(args.input, args.intent, cfg).model_dump()
        else:
            if not args.case: raise ValueError('--case required')
            result = run_task(args.root, args.case, args.key_file, args.key_env, args.retry_text_after_timeout)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        # Adapter errors intentionally contain no credentials or HTTP bodies.
        from hir_manual.gemini_api import APIError
        if isinstance(error, (APIError, ValueError, FileNotFoundError)):
            print(json.dumps({'error': str(error)}, ensure_ascii=False))
        else:
            print(json.dumps({'error': type(error).__name__, 'detail': 'See local task receipt; credential text is not logged'}))
        return 2

if __name__ == '__main__': raise SystemExit(main())
