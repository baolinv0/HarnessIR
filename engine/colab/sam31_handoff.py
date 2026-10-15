"""Explicit user-authorized SAM3.1 image-detector experiment, not SAM3 cache.

Use a separately loaded runner module so importing this entry point never
mutates the original SAM3 module's constants or existing contracts.
"""
import importlib.util
from pathlib import Path

SOURCE = Path(__file__).with_name("sam3_handoff.py")
SPEC = importlib.util.spec_from_file_location("_sam31_isolated_runner", SOURCE)
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
runner.__file__ = __file__
runner.WEIGHT_REPOSITORY = "facebook/sam3.1"
runner.WEIGHT_REVISION = "daa63191845a41281374e725f4c9e51c7a824460"
runner.CHECKPOINT_FILENAME = "sam3.1_multiplex.pt"
runner.CHECKPOINT_SHA256 = "0567debeec80ba4ac6369540c6c248025283cb3ff2b92827509e57e2b3541cb6"
runner.CHECKPOINT_BYTES = 3502755717
runner.PROFILE = "colab_sam31_tri_fp32_cpu_masks_1008_v4"
runner.RUN_PREFIX = "sam31_"
runner.PARAMETERS = dict(runner.PARAMETERS, model="SAM3.1", checkpoint_generation="SAM3.1-Multiplex-image-detector", architecture="official_multiplex_tri_backbone_detector", mlp_backend="torch_linear_activation_fp32", mask_postprocess="cpu_fp32_lazy_single_instance_bilinear_align_corners_false", mask_storage="disk_stream_v1", stop_on_systemic_failure=True)
_initialize = runner.initialize


def initialize(*args, **kwargs):
    run = _initialize(*args, **kwargs)
    deviation = "User-authorized SAM3.1 alternative; only strict image detector, not multiplex video tracking"
    if deviation not in run["deviations"]:
        run["deviations"].append(deviation)
    run["model_usage"] = "SAM3.1 image detector only"
    output = args[3] if len(args) > 3 else kwargs["output"]
    runner.write(Path(output) / "run.json", run)
    return run


runner.initialize = initialize
_prepare = runner.prepare


def platform_check(python, base, stream):
    """Record the legacy ctypes wheel tag and test native video decoding.

    No dependency failures other than this exact platform-tag issue are accepted.
    """
    import subprocess
    check = subprocess.run([str(python), "-m", "pip", "check"], capture_output=True, text=True)
    stream.write(check.stdout + check.stderr)
    if check.returncode == 0:
        return
    if check.stdout.strip() != "decord 0.6.0 is not supported on this platform" or check.stderr.strip():
        raise RuntimeError(check.stdout + check.stderr)
    code = "import cv2,numpy as np,decord,tempfile,os,json; p=tempfile.mktemp(suffix='.avi'); w=cv2.VideoWriter(p,cv2.VideoWriter_fourcc(*'MJPG'),5,(32,32)); [w.write(np.full((32,32,3),i*40,dtype=np.uint8)) for i in range(3)]; w.release(); v=decord.VideoReader(p); a=v.get_batch([0,1,2]).asnumpy(); assert a.shape==(3,32,32,3); assert abs(float(a[2].mean())-80)<5; os.unlink(p); print(json.dumps(dict(passed=True,version=decord.__version__,frames=3,shape=list(a.shape))))"
    witness = subprocess.run([str(python), "-c", code], capture_output=True, text=True, check=True)
    import json
    runner.write(base / "platform_compatibility.json", dict(pip_check_exit=check.returncode,
        pip_check_output=check.stdout.strip(), exception="decord legacy cp36 ctypes wheel tag",
        native_decode_witness=json.loads(witness.stdout.strip().splitlines()[-1]), formal_eligible=False))


def prepare(base):
    return _prepare(base, platform_check=platform_check)


runner.prepare = prepare
_worker = runner.worker


def worker(output, image_id):
    # SAM3.1 checkpoint uses the official multiplex tri-neck rather than the
    # original image builder's dual-neck. Keep every detector parameter and
    # still require strict=True; never discard unexpected checkpoint keys.
    runner.offline()
    from sam3 import model_builder
    from sam3.model import vitdet
    # Official fused MLP unconditionally emits bfloat16, incompatible with
    # fp32 fc2 on Tesla T4. Explicit profile uses equivalent unfused fp32 ops.
    vitdet.addmm_act = lambda activation, linear, value: activation()(linear(value))
    from sam3.model import sam3_image_processor as image_processor
    import torch
    class LazyFullResolutionMasks:
        def __init__(self, low, size):
            self.low, self.size = low.detach().cpu(), size
        def __len__(self):
            return len(self.low)
        def __getitem__(self, index):
            return torch.nn.functional.interpolate(self.low[index:index+1].unsqueeze(1), self.size, mode="bilinear", align_corners=False).sigmoid()[0]
    def grounding(processor, state):
        outputs = processor.model.forward_grounding(backbone_out=state['backbone_out'], find_input=processor.find_stage, geometric_prompt=state['geometric_prompt'], find_target=None)
        probabilities = (outputs['pred_logits'].sigmoid() * outputs['presence_logit_dec'].sigmoid().unsqueeze(1)).squeeze(-1)
        keep = probabilities > processor.confidence_threshold
        boxes = image_processor.box_ops.box_cxcywh_to_xyxy(outputs['pred_boxes'][keep])
        h,w=state['original_height'],state['original_width']
        state['boxes']=boxes*torch.tensor([w,h,w,h],device=processor.device)[None,:]
        state['scores']=probabilities[keep]
        state['masks_logits']=LazyFullResolutionMasks(outputs['pred_masks'][keep],(h,w))
        return state
    image_processor.Sam3Processor._forward_grounding = grounding
    model_builder._create_vit_neck = lambda position_encoding, vit_backbone, enable_inst_interactivity=False: model_builder._create_multiplex_tri_backbone(compile_mode=None, use_fa3=False, use_rope_real=False)
    model_builder._create_vl_backbone = lambda neck, text: model_builder.SAM3VLBackboneTri(scalp=0, visual=neck, text=text)
    return _worker(output, image_id)


runner.worker = worker
_gallery = runner.gallery


def gallery(output):
    path = _gallery(output)
    page = path.read_text(encoding="utf-8")
    page = page.replace("HarnessIR SAM3 evidence", "HarnessIR SAM3.1 alternative evidence")
    page = page.replace("SAM3证据：原图 / Mask叠加", "SAM3.1替代证据：原图 / Mask叠加")
    path.write_text(page, encoding="utf-8")
    return path


runner.gallery = gallery

if __name__ == "__main__":
    raise SystemExit(runner.main())
