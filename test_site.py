from pathlib import Path
import sys
import tempfile
import os
import unittest
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analysis_core import analyze, from_pairs, load_library, normalize, parse_spectra

ROOT = Path(__file__).resolve().parent
DATA = ROOT if (ROOT / 'swgdrug_library.csv').exists() else ROOT.parent.parent


class ParsingTests(unittest.TestCase):
    def test_csv_manual_and_duplicate_bins(self):
        csv = parse_spectra('mz,intensity\n58,20\n58,30\n91,100')[0]
        manual = parse_spectra('58:20, 58:30, 91:100')[0]
        np.testing.assert_allclose(csv.vector, manual.vector)
        self.assertEqual(csv.vector[48], 50)

    def test_invalid(self):
        for content in ['', '58,0', '58,-1', '58,nan', '9,20', '551,20', '58,100\nmalformed', '58:inf']:
            with self.subTest(content=content), self.assertRaises(ValueError):
                parse_spectra(content)

    def test_jcamp_records_and_scale(self):
        records = parse_spectra('##TITLE=A\n##XFACTOR=2\n##NPOINTS=2\n##XYDATA=(XY..XY)\n29,10 45.5,20\n##END=\n##TITLE=B\n##PEAK TABLE=(XY..XY)\n100 3\n##END=')
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].vector[48], 50)
        self.assertEqual(records[0].vector[81], 100)
        self.assertEqual(records[1].vector[90], 100)
        with self.assertRaises(ValueError):
            parse_spectra('##TITLE=A\n##XYDATA=(X++(Y..Y))\n58 A12\n##END=')
        with self.assertRaises(ValueError):
            parse_spectra('##TITLE=A\n##NPOINTS=2\n##XYDATA=(XY..XY)\n58 10\n##END=')

    def test_actual_hpj_matches_existing_features(self):
        lib, matrix = load_library(DATA)
        records = parse_spectra((DATA / 'JCAMP_01222025' / 'SWGDRUG 314.HPJ').read_bytes())
        self.assertEqual(len(records), len(lib))
        for i in [0, 100, 1109, 1746, 3825]:
            self.assertEqual(records[i].name, lib.iloc[i]['name'])
            np.testing.assert_allclose(records[i].vector, matrix[i], atol=.006)


class AnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library, cls.matrix = load_library(DATA)

    def test_exact_real_references(self):
        for i in [0, 100, 1109, 1746, 1814, 1835, 3825]:
            with self.subTest(index=i):
                result = analyze(self.matrix[i], self.library, self.matrix)
                self.assertIn(int(self.library.iloc[i].id), result['exact_match_entry_ids'])
                self.assertAlmostEqual(result['cosine_similarity'], 1)
                self.assertLess(result['rmse'], 1e-7)

    def test_known_real_signal_mixture(self):
        for ratio in [.2, .7, .95]:
            result = analyze(normalize(self.matrix[1746] * ratio + self.matrix[1109] * (1-ratio)), self.library, self.matrix)
            weights = {c['entry_id']: c['fit_weight_percent'] for c in result['components']}
            self.assertAlmostEqual(weights.get(1747, 0), ratio * 100, places=4)
            self.assertAlmostEqual(weights.get(1110, 0), (1-ratio) * 100, places=4)
            self.assertLess(result['rmse'], 1e-7)
            self.assertAlmostEqual(sum(weights.values()), 100)

    def test_duplicates_and_unmatched(self):
        matrix = np.zeros((3, 541))
        matrix[0, 40] = 100
        matrix[1, 40] = 100
        matrix[2, 60] = 100
        lib = pd.DataFrame({'id': [1, 2, 3], 'name': ['A', 'B', 'C'], 'formula': ['X']*3, 'mw': [1.0]*3})
        exact = analyze(matrix[0], lib, matrix)
        self.assertEqual(exact['exact_match_entry_ids'], [1, 2])
        self.assertEqual(exact['components'][0]['indistinguishable_entry_ids'], [1, 2])
        query = np.zeros(541)
        query[80] = 100
        result = analyze(query, lib, matrix)
        self.assertEqual(result['status'], 'Inconclusive library match')
        self.assertEqual(result['components'], [])
        self.assertLess(result['r_squared'], 0)
        np.testing.assert_allclose(result['residual'], query)


class WebsiteTests(unittest.TestCase):
    def test_workflows(self):
        from streamlit.testing.v1 import AppTest
        test_store = DATA / '__pycache__' / 'test_history.sqlite3'
        os.environ['SPECTRALAB_HISTORY_PATH'] = str(test_store)
        target = ROOT / 'streamlit_app.py' if (ROOT / 'streamlit_app.py').exists() else ROOT / 'app.py'
        app = AppTest.from_file(str(target), default_timeout=60).run()
        self.assertFalse(app.exception, str(app.exception))
        main_tabs = ['Overview', 'Spectrum analysis', 'Mixture simulator', 'Batch upload', 'Reference library', 'History', 'Evidence notebook', 'Methodology']
        self.assertEqual([t.label for t in app.tabs if t.label in main_tabs], main_tabs)
        self.assertTrue({'Signal canvas', 'Blind recovery challenge', 'Ratio sweep'}.issubset({t.label for t in app.tabs}))
        app.button[0].click().run()
        self.assertFalse(app.exception, str(app.exception))
        self.assertEqual(app.session_state['report']['best_entry_id'], 1747)
        run_id = app.session_state['report']['run_id']
        app.text_input[0].set_value('[').run()
        self.assertFalse(app.exception, str(app.exception))
        self.assertEqual(app.session_state['report']['run_id'], run_id)
        app.radio[0].set_value('Paste peaks').run()
        app.text_area[0].set_value('58:-10').run()
        next(b for b in app.button if b.label == 'Analyze peaks').click().run()
        self.assertFalse(app.exception, str(app.exception))
        self.assertEqual(app.session_state['report']['run_id'], run_id)
        next(b for b in app.button if b.label == 'Simulate and analyze').click().run()
        self.assertFalse(app.exception, str(app.exception))
        report = app.session_state['simulation_report']
        self.assertLess(report['rmse'], 1e-7)
        self.assertEqual(report['simulation_settings']['experiment']['settings']['seed'], 42)
        app.slider(key='studio_noise').set_value(2.0).run()
        app.checkbox(key='studio_third_enabled').check().run()
        self.assertFalse(app.exception, str(app.exception))
        next(b for b in app.button if b.label == 'Run 11-step ratio sweep').click().run()
        self.assertFalse(app.exception, str(app.exception))
        self.assertEqual(len(app.session_state['studio_sweep']['rows']), 11)
        self.assertEqual(app.session_state['simulation_report']['run_id'], report['run_id'])
        next(b for b in app.button if b.label == 'Restore saved result').click().run()
        self.assertFalse(app.exception, str(app.exception))
        self.assertIn('restored_report', app.session_state)


if __name__ == '__main__':
    unittest.main()
