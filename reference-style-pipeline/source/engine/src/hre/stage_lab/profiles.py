"""Condition formats to test, not claims that a model is better at a task."""
from copy import deepcopy

PROFILES = {
    'generic': {
        'id': 'generic', 'name': '通用编辑条件',
        'condition_format': 'natural_language',
        'guidance': 'Write an actionable editing instruction grounded in A. B supplies appearance only.',
    },
    'flux3_klein': {
        'id': 'flux3_klein', 'name': 'FLUX 3 Klein · PUP',
        'condition_format': 'pup_caption',
        'guidance': 'Prepare a brief for the native PUP or an expanded image-edit instruction. Preserve A as the content canvas and B as an appearance donor. Choose an edit of A, not new scene composition. Bounding boxes are soft guidance, not a hard pixel mask.',
        'native_compiler': 'flux3', 'native_editor': 'flux3',
    },
    'fibo2': {
        'id': 'fibo2', 'name': 'Fibo 2.0 · VGL',
        'condition_format': 'vgl',
        'guidance': 'Prepare attribute changes and an edit instruction for bria-vgl. Keep object identity and composition grounded in A. Display tone changes are not changes of physical light-source geometry. Do not invent a native VGL schema; use the native compiler for executable VGL. Multi-image plus mask must be checked separately.',
        'native_compiler': 'fibo', 'native_editor': 'fibo',
    },
    'qwen21': {
        'id': 'qwen21', 'name': 'Qwen-Image-2.1 · PE-I2I',
        'condition_format': 'qwen_edit',
        'guidance': 'Use clear editing operations and explicit region relationships. For two images use <image1> as content and <image2> as appearance. Keep the output canvas tied to <image1>. Avoid contradictory preservation and rendering instructions. Spatial annotation is not a hard pixel guarantee.',
        'native_compiler': 'qwen_pe', 'native_editor': 'qwen21',
    },
    'firered11': {
        'id': 'firered11', 'name': 'FireRed 1.1 · Recaption',
        'condition_format': 'edit_instruction',
        'guidance': 'Write explicit image-role and region instructions. Recaption is text-only. Two-image A/B input does not trigger the native many-image crop/stitch agent. Any crop/edit/blend strategy is separate from native whole-image editing.',
        'native_compiler': 'firered', 'native_editor': 'firered',
    },
}


def get_profile(name=None):
    name = name or 'generic'
    if name not in PROFILES:
        raise ValueError(f'Unknown profile {name!r}; choose {", ".join(PROFILES)}')
    return deepcopy(PROFILES[name])
