"""ICC/domain-bound PhotoCraft CPU RGB U16 document-channel adapter.

The six upstream adjustments are channel functions, not colorimetric P3 tools.
No implicit sRGB conversion or F32 document is permitted by this protocol.
"""
from pathlib import Path
import os
import json
import subprocess
import tempfile
import numpy as np
from .color import require,image_valid,digest_bytes,encode_png16,read_png16,resolve_domain
from .evidence import array_hash,mask_valid
from .planner import instantiate

COMMIT='b1794c6e0608ccfc887213dcf58398977c5cb75e'
PROTOCOL='harnessir_photocraft_channels_v6'
DOCUMENT='RGB_U16_document_channels'
TRANSPORT='RGB_U16_LE_document_channels'
TOOLS={'exposure','curve','balance','saturation','gamma','brightness_contrast'}

class PhotoCraftAdapter:
    simulation=False
    def __init__(self,executable,expected_sha256,timeout=120,domain=None):
        self.domain=resolve_domain(domain)
        self.working_icc_sha256=digest_bytes(self.domain.profile)
        self.executable=Path(executable).resolve();self.expected_sha256=expected_sha256;self.timeout=timeout
        require(self.executable.is_file(),'PhotoCraft worker unavailable; build separately and configure binary hash')
        self._check_binary()
        p=subprocess.run([str(self.executable),'--capabilities'],capture_output=True,text=True,timeout=timeout,check=True,env=self._env())
        caps=json.loads(p.stdout)
        require(caps.get('commit')==COMMIT and caps.get('protocol')==PROTOCOL and
                caps.get('adapter_version')=='p3-material-controller-v6' and caps.get('backend')=='cpu' and
                caps.get('document')==DOCUMENT and caps.get('input')==TRANSPORT and caps.get('output')==TRANSPORT and
                caps.get('implicit_color_transform') is False and set(caps.get('tools',[]))==TOOLS and
                caps.get('balance_parameter_range')==[-100,100],
                'backend identity/domain mismatch')
        supported=caps.get('supported_domains')
        require(isinstance(supported,dict) and self.working_icc_sha256 in supported.get(self.domain.id,[]),
                'backend unsupported domain/working ICC')
        self.capabilities=caps
        self.identity={'commit':COMMIT,'binary_sha256':expected_sha256,'protocol':PROTOCOL,
                       'adapter_version':'p3-material-controller-v6','document':DOCUMENT,'domain':self.domain.identity,
                       'working_icc_sha256':self.working_icc_sha256,'backend':'cpu'}
        self.receipts=[]
    def _check_binary(self):require(digest_bytes(self.executable.read_bytes())==self.expected_sha256,'worker binary changed')
    def _env(self):return {'PATH':os.environ.get('PATH',''),'RAYON_NUM_THREADS':'1','LC_ALL':'C','HOME':'/nonexistent'}
    def inspect_capabilities(self):
        return {**self.capabilities,'selected_domain':self.domain.identity,'status':'code_verified',
                'runtime_acceptance':'requires domain-bound M0 probe receipt',
                'limits':['ICC-bound U16 opaque RGB document channels only','no PS numerical equivalence',
                          'exposure gamma2.2 is not physical P3 EV; saturation grey/balance luminosity are not P3 Y',
                          'full frame CPU; no band rendering','outside SDR rejected']}
    def render_from_source(self,source,plan,values,masks):
        image_valid(source);ops=instantiate(plan,values);self._check_binary()
        with tempfile.TemporaryDirectory(prefix='hre-photocraft-v6-') as directory:
            root=Path(directory)
            quantized=np.rint(source*65535).astype('<u2');quantized.tofile(root/'source.u16')
            (root/'working.icc').write_bytes(self.domain.profile)
            request={'protocol':PROTOCOL,'width':source.shape[1],'height':source.shape[0],
                     'domain_id':self.domain.id,'working_icc_sha256':self.working_icc_sha256,'operations':[]}
            for i,op in enumerate(ops):
                mask=op['mask_id']
                if mask is not None:
                    mask_valid(masks[mask],source.shape[:2]);masks[mask].astype('<f4').tofile(root/f'mask{i}.f32')
                request['operations'].append({'tool':op['tool'],'values':op['values'],'mask':mask is not None})
            (root/'request.json').write_text(json.dumps(request,allow_nan=False))
            p=subprocess.run([str(self.executable)],cwd=root,env=self._env(),capture_output=True,text=True,timeout=self.timeout,check=True)
            receipt=json.loads(p.stdout)
            require(receipt.get('commit')==COMMIT and receipt.get('protocol')==PROTOCOL and
                    receipt.get('adapter_version')=='p3-material-controller-v6' and receipt.get('backend')=='cpu' and
                    receipt.get('warnings')==[] and receipt.get('width')==source.shape[1] and receipt.get('height')==source.shape[0] and
                    receipt.get('document')==DOCUMENT and receipt.get('input')==TRANSPORT and receipt.get('output')==TRANSPORT and
                    receipt.get('domain_id')==self.domain.id and receipt.get('working_icc_sha256')==self.working_icc_sha256 and
                    receipt.get('implicit_color_transform') is False,'render receipt mismatch/warnings')
            raw=(root/'output.u16').read_bytes();require(len(raw)==source.size*2,'native output byte count')
            out=np.frombuffer(raw,'<u2').reshape(source.shape).astype(np.float64)/65535;image_valid(out)
            self.receipts.append({**receipt,'input_pixels':array_hash(source),'input_u16_sha256':digest_bytes(quantized.tobytes()),
                                  'output_pixels':array_hash(out),'output_u16_sha256':digest_bytes(raw),
                                  'domain':self.domain.identity,'operations':ops})
            return out
    def export_native(self,path,image):
        domain=resolve_domain(getattr(self,'domain',None))
        encode_png16(path,image,domain=domain);actual,meta=read_png16(path)
        require(meta.get('profile')==domain.profile,'native export profile mismatch')
        require(actual.shape==image.shape and np.max(abs(actual-image))<=.5/65535+1e-8,'native export roundtrip failed')
        return actual,{**{k:v for k,v in meta.items() if k!='profile'},'working_icc_sha256':digest_bytes(domain.profile),'domain':domain.identity}
    def replay(self,source,plan,values,masks,expected,tolerance):
        out=self.render_from_source(source,plan,values,masks)
        err=float(np.max(abs(out-expected)));domain=resolve_domain(getattr(self,'domain',None))
        return {'pass':err<=tolerance,'max_error':err,'tolerance':tolerance,'pixel_sha256':array_hash(out),
                'domain':domain.identity,'working_icc_sha256':digest_bytes(domain.profile)}
