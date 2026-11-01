"""Audited structured VLM IO: offline files or an explicitly configured loopback service.
No paid/external endpoint, shell command, environment credential or redirect support.
"""
import base64
import io
import json
from pathlib import Path
import urllib.request
import urllib.parse
import numpy as np
from PIL import Image
from .color import require,digest_bytes,preview_size,resize_float,encode_srgb,srgb_profile
from .evidence import array_hash
from .contracts import canonical,strict

class PendingResponse(RuntimeError):pass

PROMPTS={
 'discover_regions':'Inspect actual A/B and original user goal. Return labels (1..12 unique SAM3 text labels),source_observations,reference_observations,protected_properties,uncertainties (all string arrays). Identify important semantic regions and source content protections. Do not invent masks or precise measurements. No paths or commands.',
 'correspond_regions':'Inspect A/B, real SAM3 mask overlays/crops and catalog. Return regions (1..6 entries: id,a_mask,b_mask,semantic,comparability,reasons) and uncertainties. Reference only actual A and B mask IDs. Comparability is comparable/partially_comparable/not_comparable, with concrete reasons. Same semantic label may merge different instances. Do not assume alignment or comparable illumination. Do not create mask pixels.',
 'diagnose':'Explain measured reference differences after inspecting actual A/B and bilateral evidence. Return deltas,coverage,protected_properties,uncertainties,summary. Each delta: id,dimension,regions,evidence_ids,interpretation,transfer (target/preserve/exclude/uncertain),uncertainty. Evidence IDs must exist and cover both sides. Every supplied appearance dimension needs one coverage entry: dimension,status (targeted/preserve/excluded/uncertain/not_applicable),delta_ids,reason. Preserve discovered protections. Treat weak comparability explicitly; distinguish appearance from content/motion/lighting differences. Do not invent numerical measurements.',

 'contract':'Interpret actual A/B measurements and bilateral regions. Return targets/protected_properties/exclusions/uncertainties. Each target has id,kind,regions,metric,evidence_ids,tolerance_id,mandatory,direction,description. Numeric values may ONLY be observation and tolerance references. kind is interval/direction/relation/perceptual/protection. Do not invent values. Include perceptual and content protection goals. Partial comparisons only support direction. All targets will freeze before rendering. If measured_diagnosis is supplied, each target additionally needs delta_id referencing a transfer=target or preserve delta, retaining its regions and evidence; every target delta must be covered. Preserve all diagnosed protected_properties.',
 'plan':'Return operations,reason,feedback_ids. Each operation has id,tool,target_ids,mask_id,parameters,expected_effect,protect_target_ids. Only supplied tool registry, known masks and frozen target IDs are allowed. Each parameter has lower,upper,suggested,min_step. Bounds must contain identity. <=3 global, <=3 local, <=12 parameters. Feedback may change plan, never targets or measurement ROI. No paths or commands.',
 'verify':'Independent assessment: view A/B/C and native crops. Do not infer success from a plan. Return contract_sha256,source_sha256,reference_sha256,candidate_sha256,observer,target_results,content,naturalness,reference_match,native_inspected,notes,preservation_checks. Each protected property needs exactly one preservation_checks entry with item,status (pass/fail/uncertain),observation. target_results must cover each target exactly with id,status,observation. status=achieved/partial/unmet/uncertain. Other judgments=pass/fail/uncertain. native_inspected only true if supplied native views suffice; otherwise uncertain. Include text, identity, edge artifacts and omitted reference differences in notes.'}

REVIEW_DISPLAY_PROTOCOL='nominal_display_p3_to_srgb_diagnostic_v1'
# W3C CSS Color 4 sample conversion code: linear sRGB to XYZ D65.
_SRGB_TO_XYZ=np.array([[506752/1228815,87881/245763,12673/70218],
                      [87098/409605,175762/245763,12673/175545],
                      [7918/409605,87881/737289,1001167/1053270]],dtype=np.float64)

def image_parts(images,domain=None,return_provenance=False):
    result=[];records=[]
    for name,array in images.items():
        current=domain
        if isinstance(domain,dict):
            role=name.split(' ',1)[0].upper()
            require(role in domain,'review image needs explicit A/B/C domain-labelled name')
            current=domain[role]
        x=resize_float(array,preview_size(array,1024));buf=io.BytesIO()
        record=None
        if current is not None:
            require(current.id in ('srgb','display_p3'),'unsupported review display domain')
            if current.id=='display_p3':
                linear=current.xyz(x)@np.linalg.inv(_SRGB_TO_XYZ).T
                # Count before gamut clamping, independently for every native/material view.
                below=linear < -1e-12;above=linear > 1+1e-12
                oog=(below|above).any(-1)
                encoded=encode_srgb(linear)
                x=np.clip(encoded,0,1)
                frac=float(oog.mean());below_frac=float(below.any(-1).mean());above_frac=float(above.any(-1).mean())
            else:frac=below_frac=above_frac=0.
            pixels=np.rint(x*255).astype('uint8')
            Image.fromarray(pixels).save(buf,format='PNG',icc_profile=srgb_profile())
            record={'label':name,'protocol':REVIEW_DISPLAY_PROTOCOL,'working_domain':current.identity,
                    'master_view_array_sha256':array_hash(array),'master_view_shape_hwc':list(array.shape),
                    'preview_rgb8_array_sha256':array_hash(pixels),'preview_png_sha256':digest_bytes(buf.getvalue()),
                    'preview_icc_sha256':digest_bytes(srgb_profile()),'preview_domain':'sRGB encoded RGB8 with embedded canonical sRGB ICC',
                    'resize':{'max_side':1024,'filter':'BOX_float32_channel','before_color_conversion':True,'output_shape_hwc':list(pixels.shape)},
                    'out_of_srgb_gamut_fraction_before_clamp':frac,'below_srgb_zero_fraction':below_frac,'above_srgb_one_fraction':above_frac,
                    'purpose':'diagnostic_only_never_render_input_or_formal_metric',
                    'wide_gamut_review_limitation':'Clamping and RGB8 quantization may collapse wide-gamut differences. Use P3 master metrics for measured color; mark unsupported broad-gamut visual claims uncertain. Preview alone is not proof of P3 color equality.'}
        else:
            Image.fromarray(np.rint(x*255).astype('uint8')).save(buf,format='PNG')
        result.extend([{'type':'text','text':name},{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode()}}])
        if record is not None:records.append(record)
    return (result,records) if return_provenance else result

class StructuredProvider:
    simulation=False
    def __init__(self,root,config,image_domain=None):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.config=config;self.calls=0;self.image_domain=image_domain
        require(config['mode'] in ('files','local_openai'),'unsupported VLM transport')
        if config['mode']=='local_openai':
            strict(config,{'mode','url','model','timeout'})
            u=urllib.parse.urlparse(config['url'])
            require(u.scheme=='http' and u.hostname in ('127.0.0.1','::1') and not u.username and not u.password and not u.query and not u.fragment,'only literal loopback HTTP is authorized')
            require(isinstance(config['model'],str) and config['model'] and 0<config['timeout']<=300,'model/timeout required')
        else:
            strict(config,{'mode','provider'} if 'provider' in config else {'mode'})
            require('provider' not in config or config['provider']=='current_chat_offline','unsupported offline provider')
    def __call__(self,stage,context,images):
        require(stage in PROMPTS,'unknown VLM role');self.calls+=1
        instruction=PROMPTS[stage]
        if stage=='plan' and context.get('controller_protocol')=='portrait_controller_v3':
            instruction+=' Protocol portrait_controller_v3 overrides local-operation cap to 4 while keeping 6 total operations, 3 global operations and 12 total parameters. Each parameter may additionally have mode=numeric_fit (default) or visual_proposal. visual_proposal is permitted only when every target_id of its operation is perceptual/protection; its suggested value is actually rendered and held fixed for the round, not optimized or neutralized by numerical regularization. Numeric fitting prefers the interior of mandatory numerical intervals by the supplied frozen optimization_interval_margin_scale times tolerance scale, solely as search preference; frozen acceptance targets and all safety/visual gates are unchanged. Do not invent numerical perceptual scores.'
        if stage=='plan' and context.get('material_controller_protocol')=='material_controller_v4':
            require(context.get('controller_protocol')=='portrait_controller_v3' and context.get('material_region_protocol')=='manual_material_v1' and context.get('local_operation_cap')==6,'material plan context protocol mismatch')
            instruction+=' Protocol material_controller_v4 overrides local-operation cap to 6 for this explicitly versioned material run. Total operations remain at most 6, global operations at most 3, total parameters at most 12. Only supplied actual edit-mask IDs may be used; manual measurement sample regions are not automatically editing masks. All inherited controller, numeric acceptance, native safety and visual review rules remain unchanged.'
        if stage=='plan' and 'numeric_warm_start_capability' in context:
            require(context['numeric_warm_start_capability'].get('protocol')=='numeric_warm_start_v1' and context.get('controller_protocol')=='portrait_controller_v3','numeric warm-start plan context protocol mismatch')
            instruction+=' Protocol numeric_warm_start_v1: this round additionally permits optional top-level numeric_warm_start (strict boolean, default false). Set true only to request an actual seed from validated numeric_fit suggested values combined with fixed visual_proposal suggested values. The renderer always evaluates identity first, counts the seed within the unchanged preview budget, and then continues bounded numeric optimization. visual_proposal coordinates remain fixed. All renders start from original A; targets, bounds, acceptance and safety gates do not change.'
        if stage=='verify' and context.get('edge_review_protocol')=='native_edge_visual_v2':
            instruction+=' Protocol native_edge_visual_v2: additionally return edge_reviews, exactly one object per supplied edge_warnings ID with warning_id,status (pass/fail/uncertain),observation. Inspect the supplied paired A/C native crops at each warning location. Missing, fail or uncertain blocks safe delivery; native_inspected=true alone is insufficient. Return an empty edge_reviews list when no warnings exist. The warning proxy is not proof of a halo; distinguish existing content edges from new artifacts. Candidate SHA binding applies to all edge reviews.'
        if self.image_domain is not None:
            instruction+=' P3 review display protocol: supplied PNGs are explicitly transformed sRGB diagnostic derivatives, not P3 masters. Each view reports master and preview hashes, profile/domain, resize and pre-clamp out-of-gamut fraction. These previews cannot establish Display P3 match for colors clipped into sRGB. Evaluate content, naturalness and visible relationships from them; use actual P3 Lab/Y evidence for measured color. Distinguish a limited reference-style approximation plus measured metrics from unobserved wide-gamut color equality; unsupported claims must remain uncertain. Previews never feed rendering or formal measurement.'
            instruction+=' Renderer semantics: only six whitelisted PhotoCraft RGB/U16 document-channel tools are available. ICC is identity metadata, not an implicit RGB color-management transform. Exposure uses gamma 2.2 rather than physical Display P3 linear EV; saturation uses its upstream grey axis and balance preserve_luminosity is a channel rule, neither guarantees P3 Y preservation. Judge actual P3 measured output, never assume physical colorimetric behavior.'
            instruction=instruction.replace('unique SAM3 text labels','unique labels from the supplied fixed segmentation catalog').replace('real SAM3 mask overlays/crops','actual source-bound segmentation or manual-material overlays/crops')
        parts,display=image_parts(images,domain=self.image_domain,return_provenance=True)
        req={'stage':stage,'instruction':instruction,'context':context,'images':parts,'model':self.config.get('model',self.config.get('provider','offline_import'))}
        if self.image_domain is not None:req['review_display_provenance']=display
        if 'provider' in self.config:req['provider']=self.config['provider']
        request_hash=digest_bytes(canonical(req).encode());directory=self.root/f'{self.calls:02d}-{stage}-{request_hash[:12]}';directory.mkdir(exist_ok=True)
        path=directory/'request.json'
        if path.exists():require(canonical(json.loads(path.read_text()))==canonical(req),'request collision')
        else:path.write_text(canonical(req))
        response=directory/'response.json'
        if self.config['mode']=='files':
            if not response.exists():raise PendingResponse(f'Exported {path}; place bound response.json then resume same config/output')
            envelope=json.loads(response.read_text());strict(envelope,{'request_sha256','observer','payload'})
            require(envelope['request_sha256']==request_hash and envelope['observer'],'response/request binding')
            if self.config.get('provider')=='current_chat_offline':require(envelope['observer']=='current_chat_offline','current chat attribution required')
            return envelope['payload']
        # Replay completed request; an uncertain request is never silently resubmitted.
        if response.exists():return json.loads(response.read_text())['payload']
        pending=directory/'submitted.json'
        require(not pending.exists(),'VLM submission outcome uncertain: inspect service; use offline response import, do not auto-retry')
        pending.write_text(canonical({'request_sha256':request_hash}))
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):return None
        body_context={**context,'review_display_provenance':display} if self.image_domain is not None else context
        body={'model':self.config['model'],'temperature':0,'messages':[{'role':'system','content':instruction},{'role':'user','content':[{'type':'text','text':canonical(body_context)}]+req['images']}],'response_format':{'type':'json_object'}}
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        request=urllib.request.Request(self.config['url'],data=canonical(body).encode(),headers={'Content-Type':'application/json'})
        with opener.open(request,timeout=self.config['timeout']) as f:
            raw=f.read(4_000_001);require(len(raw)<=4_000_000,'VLM response size')
        (directory/'raw_response.json').write_bytes(raw)
        payload=json.loads(json.loads(raw)['choices'][0]['message']['content'])
        response.write_text(canonical({'request_sha256':request_hash,'observer':self.config['model'],'payload':payload}))
        return payload
