"""Synthetic pixel fixtures: color/identity tests, not real reference photos."""
import importlib
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image
from hre.models import HREError
from hre.reference_style.color import encode_png16, srgb_profile


class AuditTest(unittest.TestCase):
    def setUp(self):
        try:
            self.a = importlib.import_module('hre.reference_style.audit')
        except ModuleNotFoundError:
            self.fail('S1 input/color audit is not implemented')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def image(self, name='a.png', pixels=None, **kwargs):
        pixels = np.array([[[128, 64, 32], [0, 255, 0]]], dtype=np.uint8) if pixels is None else pixels
        p = self.root / name
        Image.fromarray(pixels).save(p, **kwargs)
        return p

    def spec(self, path, role='A', encoding='srgb'):
        return dict(role=role, path=str(path), encoding=encoding,
                    encoding_basis='synthetic fixture declaration',
                    base_model_version='synthetic-base-v1' if role == 'A' else None,
                    display_assumption='srgb' if encoding == 'unknown' else None)

    def test_srgb_native_derivative_is_exact_and_hashed(self):
        p = self.image()
        audit, analysis = self.a.audit_image(self.spec(p), self.root / 'out')
        self.assertEqual(audit['source_bit_depth'], 8)
        self.assertEqual(audit['source_encoding'], 'srgb')
        self.assertEqual(audit['numeric_status'], 'eligible')
        self.assertEqual(audit['native_size'], [2, 1])
        with Image.open(self.root / 'out' / audit['derivative_path']) as d, Image.open(p) as original:
            np.testing.assert_array_equal(np.asarray(d), np.asarray(original))
            self.assertEqual(d.info['icc_profile'], srgb_profile())
        self.assertAlmostEqual(float(analysis['linear_srgb'][0, 0, 0]), 0.21586050011389926)
        # Hand calculation: .2126*.2158605001 + .7152*.0512694584 + .0722*.0144438436.
        self.assertAlmostEqual(float(analysis['Y'][0, 0]), 0.08360270446096858)
        self.assertEqual(len(audit['source_file_hash']), 64)
        self.assertEqual(len(audit['source_pixel_hash']), 64)
        self.assertNotEqual(audit['source_file_hash'], audit['derivative_file_hash'])

    def test_unknown_a_is_visual_only_never_numeric_srgb(self):
        p = self.image()
        audit, analysis = self.a.audit_image(self.spec(p, encoding='unknown'), self.root / 'out')
        self.assertEqual(audit['numeric_status'], 'blocked_unknown_encoding')
        self.assertIsNone(analysis)
        self.assertEqual(audit['source_encoding'], 'unknown')
        self.assertEqual(audit['display_assumption'], 'srgb')

    def test_unknown_a_requires_explicit_display_assumption(self):
        spec = self.spec(self.image(), encoding='unknown')
        spec['display_assumption'] = None
        with self.assertRaises(ValueError):
            self.a.audit_image(spec, self.root / 'out')

    def test_b_must_be_known_srgb_and_a_must_have_base_version(self):
        p = self.image()
        for spec in [self.spec(p, role='B', encoding='unknown'), self.spec(p, role='B', encoding='display_p3'),
                     {**self.spec(p), 'base_model_version': None}]:
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                self.a.audit_image(spec, self.root / 'out')

    def test_p3_analysis_out_of_gamut_not_clipped_but_derivative_is(self):
        p = self.image(pixels=np.array([[[255, 0, 0]]], dtype=np.uint8))
        audit, analysis = self.a.audit_image(self.spec(p, encoding='display_p3'), self.root / 'out')
        self.assertGreater(float(analysis['linear_srgb'][0, 0, 0]), 1.2)
        self.assertLess(float(analysis['linear_srgb'][0, 0, 1]), 0)
        self.assertEqual(audit['gamut_clipped_pixel_fraction'], 1.0)
        self.assertTrue(audit['critical_color_judgment_requires_review'])
        with Image.open(self.root / 'out' / audit['derivative_path']) as d:
            self.assertEqual(d.getpixel((0, 0)), (255, 0, 0))

    def test_16bit_input_keeps_native_precision_before_explicit_rgb8_quantization(self):
        p = self.root / 'a.png'
        encode_png16(p, np.array([[[1 / 65535, 32768 / 65535, 1.0]]]))
        audit, analysis = self.a.audit_image(self.spec(p), self.root / 'out')
        self.assertEqual(audit['source_bit_depth'], 16)
        self.assertEqual(audit['derivative_bit_depth'], 8)
        self.assertIn('65535', audit['quantization'])
        self.assertGreater(float(analysis['linear_srgb'][0, 0, 0]), 0)
        with Image.open(self.root / 'out' / audit['derivative_path']) as d:
            self.assertEqual(d.getpixel((0, 0)), (0, 128, 255))

    def test_profile_conflict_or_unknown_profile_fails_closed(self):
        p = self.image(icc_profile=srgb_profile())
        with self.assertRaises(ValueError):
            self.a.audit_image(self.spec(p, encoding='display_p3'), self.root / 'out')
        q = self.image('bad.png', icc_profile=b'not a validated profile')
        with self.assertRaises(ValueError):
            self.a.audit_image(self.spec(q), self.root / 'out2')

    def test_orientation_recorded_without_resizing(self):
        exif = Image.Exif()
        exif[274] = 6
        p = self.image('a.jpg', exif=exif)
        audit, _ = self.a.audit_image(self.spec(p), self.root / 'out')
        self.assertEqual(audit['native_size'], [2, 1])
        self.assertEqual(audit['oriented_size'], [1, 2])
        self.assertEqual(audit['orientation'], 6)
        self.assertEqual(audit['geometry']['resize'], None)

    def test_alpha_and_same_output_overwrite_rejected(self):
        p = self.root / 'alpha.png'
        Image.new('RGBA', (1, 1)).save(p)
        with self.assertRaises(ValueError):
            self.a.audit_image(self.spec(p), self.root / 'bad')
        p = self.image()
        self.a.audit_image(self.spec(p), self.root / 'out')
        with self.assertRaises((ValueError, FileExistsError)):
            self.a.audit_image(self.spec(p), self.root / 'out')

    def test_unknown_fields_and_symlinks_rejected_without_reading(self):
        p = self.image()
        link = self.root / 'link.png'
        try:
            link.symlink_to(p)
        except OSError as exc:
            if getattr(exc, 'winerror', None) == 1314:
                self.skipTest('Windows account lacks symbolic-link creation privilege')
            raise
        for spec in [self.spec(link), {**self.spec(p), 'raw_x': '/must/not/read'}]:
            with self.subTest(spec=spec), self.assertRaises((ValueError, HREError)):
                self.a.audit_image(spec, self.root / 'out')


if __name__ == '__main__':
    unittest.main()
