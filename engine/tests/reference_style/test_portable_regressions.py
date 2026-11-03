"""Real temporary synthetic cases for cross-platform and decision regressions."""
import unittest
import test_s4 as fixture
from hre.reference_style import coordinator as co


class PortableRegressionTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.S4Test()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_candidate_asset_paths_are_portable_and_case_remains_readable(self):
        case = self.fixture
        case.prepare()
        self.assertTrue(case.derived['payload']['assets'])
        for asset in case.derived['payload']['assets']:
            self.assertNotIn('\\', asset['path'])
        self.assertEqual(co.status(case.case)['sample_id'], 's2fixture')

    def test_known_major_geometry_rejects_even_before_calibration(self):
        case = self.fixture
        case.configured_evaluation(False)
        spec = case.facts_spec()
        spec['content_spatial']['geometry'] = {'severity': 'major', 'confidence': 'high'}
        facts = case.review.freeze_facts(case.case, spec)
        self.assertEqual(case.decision(facts)['payload']['status'], 'rejected')


if __name__ == '__main__':
    unittest.main()
