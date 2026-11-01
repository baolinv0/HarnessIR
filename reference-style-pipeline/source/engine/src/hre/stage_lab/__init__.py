"""Independent, replayable model tests for reference image enhancement."""

STAGES = ('diagnose', 'plan', 'compile', 'execute', 'judge')
STAGE_LABELS = {
    'diagnose': '1 · 差异观察', 'plan': '2 · Action 规划',
    'compile': '3 · 原生条件', 'execute': '4 · 图像执行', 'judge': '5 · 结果判别',
}


def normalize_stage(value: str) -> str:
    aliases = dict(zip(('d', 'p', 'c', 'e', 'j'), STAGES))
    aliases.update({str(i + 1): s for i, s in enumerate(STAGES)})
    stage = aliases.get(value.lower(), value.lower())
    if stage not in STAGES:
        raise ValueError(f'Unknown stage {value!r}; choose {", ".join(STAGES)}')
    return stage
