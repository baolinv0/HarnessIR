"""Native API wiring tests; these do not run or assess model weights."""
from contextlib import nullcontext
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import warnings

import pytest
from PIL import Image

from hre.stage_lab import native_workers as workers


@pytest.fixture
def native_request(tmp_path):
    images = []
    for role, size, color in [('A', (24, 16), 'red'), ('B', (16, 24), 'blue')]:
        path = tmp_path / f'{role}.png'
        Image.new('RGB', size, color).save(path)
        images.append({'role': role, 'path': str(path)})
    return {'stage': 'execute', 'prompt': 'task template', 'images': images,
            'context': {'upstream': [{'stage': 'compile', 'data': {'native_prompt': 'EXACT native caption'},
                                      'text': 'raw compiler output'}]}, 'parameters': {}, 'profile': {}}


def test_compiler_receives_full_plan_and_editor_prefers_selected_compiler(native_request):
    plan = {'actions': [{'operation': 'lift shadows'}], 'constraints': ['keep background dark']}
    native_request['context']['upstream'].insert(0, {'stage': 'plan', 'data': plan})
    assert json.loads(workers.instruction(native_request)) == plan
    prompt, _, compiled = workers.compiled_condition(native_request)
    assert prompt == 'EXACT native caption'
    assert compiled


def test_flux_selected_compile_skips_pup_and_keeps_reference_order(native_request, tmp_path, monkeypatch):
    calls = {}

    def models(dits, **kwargs):
        calls['models'] = (dits, kwargs)
        return object()

    def generate(model, variant, prompt, images, **kwargs):
        calls['generate'] = (variant, prompt, [im.size for im in images], kwargs)
        return Image.new('RGB', (32, 16)), {'prompt': prompt, 'upsampled': False}

    monkeypatch.setitem(sys.modules, 'flux3', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'flux3.generate', SimpleNamespace(Models=models, generate=generate))
    monkeypatch.setitem(sys.modules, 'flux3.pipeline',
                        SimpleNamespace(dit_path=lambda *_: Path('/weights/dit'), WEIGHTS=Path('/weights')))
    result = workers.run_native('flux3', native_request, tmp_path / 'response.json')
    assert calls['models'][1]['pup'] is None
    assert calls['generate'] == ('distilled', 'EXACT native caption', [(24, 16), (16, 24)],
                                 {'seed': 42, 'pup': False})
    assert Image.open(result['images'][0]).size == (32, 16)
    assert result['metadata']['compiled_input']


def fake_pipeline(monkeypatch):
    calls = {}

    class Pipeline:
        def __call__(self, **kwargs):
            calls.update(kwargs)
            return SimpleNamespace(images=[Image.new('RGB', (40, 20))])

    monkeypatch.setattr(workers, '_load_pipeline', lambda cls, checkpoint, params, **options:
                        (Pipeline(), SimpleNamespace(inference_mode=nullcontext), 'seeded-generator'))
    monkeypatch.setitem(sys.modules, 'diffusers', SimpleNamespace(
        BriaFibo2Pipeline=object, QwenImage21Pipeline=object, QwenImageEditPlusPipeline=object))
    return calls


def test_fibo_compiles_native_vgl_and_reuses_it_without_compile(native_request, tmp_path, monkeypatch):
    calls = fake_pipeline(monkeypatch)
    scene = {'short_description': 'A with softer highlights', 'objects': []}
    compiles = []

    def modify(payload, **kwargs):
        compiles.append(payload)
        return SimpleNamespace(model_dump=lambda **_: scene)

    monkeypatch.setitem(sys.modules, 'bria_vgl', SimpleNamespace(modify=modify, DEFAULT_LLM='test/compiler'))
    monkeypatch.setitem(sys.modules, 'bria_vgl.dialects', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'bria_vgl.dialects.thales',
                        SimpleNamespace(EditImages=SimpleNamespace, EditImageWithMask=SimpleNamespace))
    native_request['stage'] = 'compile'
    native_request['context'] = {'instruction': 'Soften highlights using B.'}
    compiled = workers.run_native('fibo', native_request, tmp_path / 'compile.json')
    assert compiled['data']['vgl'] == scene
    assert compiles[0].prompt == 'Soften highlights using B.'
    assert [im.size for im in compiles[0].images] == [(24, 16), (16, 24)]
    native_request['stage'] = 'execute'
    native_request['context'] = {'upstream': [{'stage': 'compile', **compiled}]}
    native_request['parameters'] = {'fonts': ['font.otf']}
    workers.run_native('fibo', native_request, tmp_path / 'execute.json')
    assert len(compiles) == 1
    assert json.loads(calls['prompt']) == scene
    assert len(calls['image']) == 2
    assert calls['fonts'] == ['font.otf']


def test_qwen_canvas_and_compiled_text_reach_editor(native_request, tmp_path, monkeypatch):
    calls = fake_pipeline(monkeypatch)
    native_request['context']['upstream'][-1]['data'] = {
        'rewritten_prompt': 'Native Qwen edit', 'ratio_follow': '<image1>', 'parse_ok': True}
    result = workers.run_native('qwen21', native_request, tmp_path / 'response.json')
    assert calls['prompt'] == 'Native Qwen edit'
    assert (calls['width'], calls['height']) == (24, 16)
    assert [im.size for im in calls['image']] == [(24, 16), (16, 24)]
    assert result['metadata']['checkpoint'] == 'Qwen/Qwen-Image-2.1'
    assert Image.open(result['images'][0]).size == (40, 20)


def test_qwen_pe_uses_official_runner_and_only_records_final_answer(native_request, tmp_path, monkeypatch):
    class Model:
        def to(self, device):
            return self

        def eval(self):
            return self

    calls = {}
    answer = '{"rewritten_prompt":"Qwen edit","ratio_follow":"<image1>"}'
    profile = SimpleNamespace(image_max_pixels=1024, max_new_tokens=24000, temperature=1.0,
                              top_p=.95, top_k=20, presence_penalty=0.)

    def rewrite(model, processor, messages, **kwargs):
        calls.update(messages=messages, sampling=kwargs)
        return 'private intermediate reasoning', answer

    monkeypatch.setattr(workers, '_torch', lambda _: (None, 'bfloat16', 'cuda', None))
    monkeypatch.setitem(sys.modules, 'transformers', SimpleNamespace(
        AutoModelForImageTextToText=SimpleNamespace(from_pretrained=lambda *a, **k: Model()),
        AutoProcessor=SimpleNamespace(from_pretrained=lambda *a: object())))
    monkeypatch.setitem(sys.modules, 'pe_core', SimpleNamespace(
        load_system_prompt=lambda *a: 'official template', get_profile=lambda *a: profile,
        load_image=lambda path, size: str(path), build_messages=lambda system, prompt, images: [system, prompt, images],
        parse_answer=lambda text, p: {'positive_prompt': 'Qwen edit', 'ratio_follow': '<image1>', 'parse_ok': True}))
    monkeypatch.setitem(sys.modules, 'run_transformers', SimpleNamespace(rewrite=rewrite))
    native_request.update(stage='compile', context={'instruction': 'Transfer B appearance to A.'},
                          parameters={'system_prompt': str(tmp_path / 'system.txt')})
    result = workers.run_native('qwen_pe', native_request, tmp_path / 'response.json')
    assert calls['messages'][1] == 'Transfer B appearance to A.'
    assert calls['sampling']['presence_penalty'] == 0
    assert result['data']['rewritten_prompt'] == 'Qwen edit'
    assert result['text'] == answer
    assert 'private intermediate reasoning' not in json.dumps(result)


def test_firered_executes_exact_prompt_with_version_11(native_request, tmp_path, monkeypatch):
    calls = fake_pipeline(monkeypatch)
    result = workers.run_native('firered', native_request, tmp_path / 'response.json')
    assert calls['prompt'] == 'EXACT native caption'
    assert calls['true_cfg_scale'] == 4.0
    assert result['metadata']['checkpoint'] == 'FireRedTeam/FireRed-Image-Edit-1.1'


def test_firered_compile_detects_official_silent_fallback(native_request, tmp_path, monkeypatch):
    def recaption(prompt, groups, target_length):
        warnings.warn('Skipping recaption: no client configured.', RuntimeWarning)
        return prompt

    monkeypatch.setitem(sys.modules, 'agent', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'agent.recaption', SimpleNamespace(recaption=recaption))
    monkeypatch.setitem(sys.modules, 'agent.config', SimpleNamespace(GEMINI_MODEL_NAME='test/compiler'))
    native_request['stage'] = 'compile'
    native_request['context'] = {'instruction': 'Edit image 1 using image 2 appearance.'}
    with pytest.raises(RuntimeError, match='Recaption failed'):
        workers.run_native('firered', native_request, tmp_path / 'response.json')


def test_cli_emits_contract_without_loading_unselected_models(native_request, tmp_path, monkeypatch):
    monkeypatch.setattr(workers, '_flux3', lambda *args: workers._result('native caption', {'native_prompt': 'native caption'}))
    request_file, output = tmp_path / 'native_request.json', tmp_path / 'response.json'
    request_file.write_text(json.dumps(native_request), encoding='utf-8')
    assert workers.main(['flux3', '--request', str(request_file), '--output', str(output)]) == 0
    assert json.loads(output.read_text()) == {'text': 'native caption', 'data': {'native_prompt': 'native caption'},
                                              'images': [], 'metadata': {}, 'usage': {}}
