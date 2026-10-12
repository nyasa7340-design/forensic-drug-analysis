from pathlib import Path
import sys
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from simulation_core import simulate_signals, fingerprint_diagnostics, ratio_sweep


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.spectra = np.zeros((3, 541))
        self.spectra[0, [20, 30, 40]] = [100, 60, 20]
        self.spectra[1, [20, 50, 60]] = [10, 100, 30]
        self.spectra[2, [70, 80, 90]] = [100, 50, 30]

    def test_three_component_canvas(self):
        result = simulate_signals(self.spectra, [60, 30, 10])
        np.testing.assert_allclose(np.sum(result['contributions'], axis=0), result['clean'])
        np.testing.assert_allclose(result['clean'], result['observed'])
        self.assertAlmostEqual(max(result['clean']), 100)

    def test_reproducible_challenge(self):
        a = simulate_signals(self.spectra, [60, 30, 10], 2, 40, 3, 123)
        b = simulate_signals(self.spectra, [60, 30, 10], 2, 40, 3, 123)
        self.assertEqual(a, b)
        self.assertGreater(a['distortion_rmse'], 0)
        self.assertEqual(len(a['added_mz']), 3)
        self.assertEqual(len(a['dropped_mz']), 3)
        self.assertTrue(np.isfinite(a['observed']).all())
        self.assertTrue((np.asarray(a['observed']) >= 0).all())
        different = simulate_signals(self.spectra, [60, 30, 10], 2, 40, 3, 124)
        self.assertNotEqual(a['observed'], different['observed'])

    def test_invalid_weights(self):
        for shares in [[70, 20, 0], [-10, 100, 10]]:
            with self.assertRaises(ValueError):
                simulate_signals(self.spectra, shares)

    def test_overlap_and_rank(self):
        result = fingerprint_diagnostics(self.spectra, ['A','B','C'])
        np.testing.assert_allclose(np.diag(result['similarities']), 1)
        self.assertEqual(result['similarities'][0][2], 0)
        self.assertGreater(result['condition_number'], 1)
        for row in result['contrast_ions']:
            self.assertGreater(row['contrast'], 0)
        duplicate = fingerprint_diagnostics(self.spectra[[0,0]], ['A','B'])
        self.assertIsNone(duplicate['condition_number'])
        self.assertEqual(duplicate['contrast_ions'], [])

    def test_ratio_sweep_exact_recovery(self):
        rows = ratio_sweep(self.spectra[:2], ['A','B'])
        self.assertEqual(len(rows), 11)
        self.assertLess(max(r['A_absolute_error_pp'] for r in rows), 1e-8)
        self.assertLess(max(r['fit_rmse'] for r in rows), 1e-8)


if __name__ == '__main__':
    unittest.main()
