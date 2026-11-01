"""Narrow regressions for remaining r2 review blockers; no actual model outputs."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zlib

import numpy as np
from PIL import Image
from hre.reference_style import audit, contracts as ct
from hre.tool_retouch.color import _chunks, encode_png16, srgb_profile
from test_r2_regressions import chunk, context


class FinalScopeRegression(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def fixture(self,depth,name,body=None):
        p=self.root/(name+'.png')
        if depth==16:encode_png16(p,np.array([[[0.5,0.25,0.125]]]))
        else:Image.new('RGB',(1,1),(128,64,32)).save(p)
        if body is not None:
            raw=p.read_bytes();raw=raw[:8]+b''.join(chunk(t,b) for t,b in _chunks(raw) if t!=b'iCCP')
            p.write_bytes(raw[:33]+chunk(b'iCCP',body)+raw[33:])
        return p

    def do_audit(self,p,out):
        spec=dict(role='A',path=str(p),encoding='srgb',encoding_basis='synthetic fixture',
                  base_model_version='fixture',display_assumption=None)
        return audit.audit_image(spec,out)

    def test_present_invalid_iccp_rejects_cleanly_before_writes_at_both_depths(self):
        cases=[b'bad\0\0not-zlib-compressed-data',b'empty\0\0'+zlib.compress(b''),
               b'truncated\0\0'+zlib.compress(srgb_profile()[:100]),
               b'incomplete\0\0'+zlib.compress(srgb_profile())[:-4],
               b'method\0\1'+zlib.compress(srgb_profile()),
               b'extra\0\0'+zlib.compress(srgb_profile())+b'trailing',
               b'noname-or-method',b'\0\0'+zlib.compress(srgb_profile())]
        for depth in (8,16):
            for index,body in enumerate(cases):
                name=f'bad{depth}_{index}';p=self.fixture(depth,name,body);out=self.root/(name+'_out')
                with self.subTest(depth=depth,index=index):
                    try:self.do_audit(p,out)
                    except ValueError:pass
                    except Exception as exc:self.fail(f'expected structured ValueError, got {type(exc).__name__}: {exc}')
                    else:self.fail('present invalid ICC was treated as supported/absent')
                    self.assertFalse(out.exists())

    def test_valid_profile_and_explicit_untagged_inputs_remain_supported(self):
        for depth in (8,16):
            p=self.fixture(depth,'valid'+str(depth),b'canonical\0\0'+zlib.compress(srgb_profile()))
            result,_=self.do_audit(p,self.root/('valid_out'+str(depth)))
            self.assertEqual(result['numeric_status'],'eligible')
            self.assertEqual(result['source_png_color_metadata'].get('iCCP_profile_hash'),result['source_icc_hash'])
            self.assertEqual(result['source_png_color_metadata'].get('iCCP_profile_bytes'),len(srgb_profile()))
        p=self.fixture(8,'untagged');result,_=self.do_audit(p,self.root/'untagged_out')
        self.assertEqual(result['numeric_status'],'eligible');self.assertIsNone(result['source_icc_hash'])

    def test_whole_face_and_exposed_skin_allowed_but_intra_face_units_rejected(self):
        for sem,unit in [('face','whole_semantic_object'),('exposed_skin','whole_material'),
                         ('hair','whole_semantic_object'),('clothing','whole_material')]:
            value=context();value['targets'][0].update(unit=unit,region_refs=[
                dict(role=role,semantic_class=sem,instance_index=1) for role in ('A','B')])
            try:result=ct.execution_context(value)
            except ValueError as exc:self.fail(f'whole semantic class {sem} unavailable: {exc}')
            self.assertEqual(result['targets'][0]['region_refs'][0]['semantic_class'],sem)
            self.assertEqual(result['preservation_requirements'],ct.PRESERVATION)
        for sem in ('face_shadow','face_highlight','left_cheek_highlight','eye','nose'):
            value=context();value['targets'][0].update(unit='whole_semantic_object',region_refs=[
                dict(role=role,semantic_class=sem,instance_index=1) for role in ('A','B')])
            with self.subTest(semantic=sem),self.assertRaises(ValueError):ct.execution_context(value)

    def test_valid_container_icc_requires_matching_decoder_metadata(self):
        p=self.fixture(8,'valid_lost_metadata',b'canonical\0\0'+zlib.compress(srgb_profile()))
        original_open=Image.open
        def missing_metadata(*args,**kwargs):
            im=original_open(*args,**kwargs)
            im.info['icc_profile']=None  # Deliberate decoder-boundary fault, real image decoding.
            return im
        out=self.root/'inconsistent_decoder'
        with patch.object(audit.Image,'open',side_effect=missing_metadata),self.assertRaises(ValueError):
            self.do_audit(p,out)
        self.assertFalse(out.exists())


if __name__=='__main__':unittest.main()
