import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'research/model_aware_20261024/scripts/analyze_pairs.py'


class PairedAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(), 'Paired analysis implementation is missing')
        spec = importlib.util.spec_from_file_location('paired_analysis', SCRIPT)
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_replicates_are_averaged_within_scene_before_bootstrap(self):
        rows=[]
        # Scene a has two images and more replicates; b has one image.
        for scene,sample,reps,delta in [('a','a1',3,2),('a','a2',3,2),('b','b1',1,6)]:
            for rep in range(reps):
                for arm,value in [('shared',10),('aware',10+delta)]:
                    rows.append(dict(scene_id=scene,sample_id=sample,replicate=str(rep),
                                     model='qwen',arm=arm,metric='PSNR',value=str(value),status='ok'))
        result=self.mod.compare(rows,'qwen','shared','aware','PSNR',1,seed=9,draws=1000)
        self.assertEqual(result['n_scenes'],2)
        self.assertEqual(result['effect'],4)
        self.assertEqual(result['ci95'],[2,6])

    def test_unmatched_rows_cannot_silently_change_the_paired_cohort(self):
        rows=[dict(scene_id='a',sample_id='s',replicate='0',model='qwen',
                   arm='shared',metric='PSNR',value='10',status='ok')]
        with self.assertRaises(ValueError):
            self.mod.compare(rows,'qwen','shared','aware','PSNR',1)

    def test_error_rows_cannot_become_zero_scores(self):
        rows=[dict(scene_id='a',sample_id='s',replicate='0',model='qwen',
                   arm=arm,metric='PSNR',value=value,status=status)
              for arm,value,status in [('shared','10','ok'),('aware','','error')]]
        with self.assertRaises(ValueError):
            self.mod.compare(rows,'qwen','shared','aware','PSNR',1)

    def test_interaction_uses_within_scene_difference_of_policy_effects(self):
        rows=[]
        for scene in ['a','b']:
            for model,delta in [('qwen',3),('nb2',1)]:
                for arm,value in [('shared',10),('aware',10+delta)]:
                    rows.append(dict(scene_id=scene,sample_id=scene,replicate='0',
                                     model=model,arm=arm,metric='PSNR',value=str(value),status='ok'))
        result=self.mod.interaction(rows,'qwen','nb2','shared','aware','PSNR',1,draws=100)
        self.assertEqual(result['effect'],2)
        self.assertEqual(result['ci95'],[2,2])

    def test_both_arms_omitting_a_frozen_sample_is_rejected(self):
        rows=[]
        for scene in ['a','b']:
            for arm in ['shared','aware']:
                rows.append(dict(scene_id=scene,sample_id=scene,replicate='0',
                                 model='qwen',arm=arm,metric='PSNR',value='10',status='ok'))
        with self.assertRaises(ValueError):
            self.mod.compare(rows,'qwen','shared','aware','PSNR',1,
                             expected=[('a','a','0'),('b','b','0'),('c','c','0')])


if __name__ == '__main__': unittest.main()
