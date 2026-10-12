from pathlib import Path
import sys
import json
import sqlite3
import unittest
import uuid
import zipfile
import io
import os

sys.path.insert(0,str(Path(__file__).parent))
from evidence_notebook import NotebookStore
ROOT = Path(__file__).parent
DATA = ROOT if (ROOT/'swgdrug_library.csv').exists() else ROOT.parent.parent
TEST_DATA = DATA/'__pycache__'/'notebook_tests'


class NotebookTests(unittest.TestCase):
    def setUp(self):
        self.store = NotebookStore(TEST_DATA / uuid.uuid4().hex)
        self.case = self.store.create('Case <one>', 'Sample 7', 'Analyst A')
        self.report = {'run_id':'test-run','sample':'Test specimen','timestamp':'2026-10-12T14:00:00+05:30','source':'Test data',
                       'status':'Screening only','best_name':'Test reference','cosine_similarity':1.0,'rmse':0.0,
                       'query':[0.0]*541,'reconstructed':[0.0]*541,'residual':[0.0]*541,'library_sha256':'test-checksum'}
        self.report['query'][72] = self.report['reconstructed'][72] = 100

    def test_snapshot_and_persistence(self):
        self.assertTrue(self.store.link(self.case,self.report))
        self.assertFalse(self.store.link(self.case,self.report))
        self.report['sample'] = 'Changed later'
        restored = NotebookStore(self.store.directory)
        bundle = restored.bundle(self.case)
        self.assertEqual(bundle['analyses'][0]['report']['sample'],'Test specimen')
        self.assertEqual(len(bundle['activity']),2)

    def test_files_and_export(self):
        payload = b'mz,intensity\n82,100\n'
        attachment = self.store.attach(self.case,'../../evidence.csv',payload,'Chromatogram','Observation <script>alert(1)</script>')
        self.assertEqual(self.store.attachment(self.case,attachment)['name'],'evidence.csv')
        with self.assertRaises(ValueError):
            self.store.attach(self.case,'duplicate.csv',payload,'Chromatogram','')
        self.store.link(self.case,self.report)
        self.store.annotate(self.case,'test-run',82,'Conflicts with interpretation','A conflicting observation')
        self.store.update(self.case,'Reviewer','Awaiting review','Tentative result','Requires further evidence')
        package, html, content = self.store.export(self.case)
        self.assertNotIn('<script>alert(1)</script>',html)
        self.assertIn('&lt;script&gt;',html)
        data = json.loads(content)
        self.assertEqual(data['case']['status'],'Awaiting review')
        self.assertEqual(data['annotations'][0]['mz'],82)
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            self.assertIn('report.html',archive.namelist())
            self.assertEqual(archive.read(f'attachments/{attachment}.csv'),payload)
            self.assertTrue(all('..' not in name for name in archive.namelist()))

    def test_invalid_annotations_and_files(self):
        with self.assertRaises(ValueError):
            self.store.annotate(self.case,'not-linked',82,'Unresolved observation','Note')
        with self.assertRaises(ValueError):
            self.store.attach(self.case,'file.exe',b'content','Other supporting evidence','')
        with self.assertRaises(ValueError):
            self.store.attach(self.case,'file.txt',b'','Other supporting evidence','')
        with self.assertRaises(ValueError):
            self.store.create(' ')
        with self.assertRaises(ValueError):
            self.store.bundle('missing-case')

    def test_corrupted_attachment(self):
        attachment = self.store.attach(self.case,'spectrum.txt',b'original','FTIR evidence','')
        with self.store.connect() as conn:
            conn.execute('UPDATE attachments SET payload=? WHERE id=?',(b'changed',attachment))
        with self.assertRaises(ValueError):
            self.store.attachment(self.case,attachment)
        with self.assertRaises(ValueError):
            self.store.export(self.case)


class NotebookWebsiteTests(unittest.TestCase):
    def test_create_link_annotate_review(self):
        from streamlit.testing.v1 import AppTest
        test = NotebookTests()
        test.setUp()
        directory = TEST_DATA / 'ui' / uuid.uuid4().hex
        directory.mkdir(parents=True)
        os.environ['SPECTRALAB_NOTEBOOK_DIR'] = str(directory / 'notebooks')
        os.environ['SPECTRALAB_HISTORY_PATH'] = str(directory / 'history.sqlite3')
        with sqlite3.connect(directory / 'history.sqlite3') as conn:
            conn.execute('CREATE TABLE runs(id TEXT PRIMARY KEY,timestamp TEXT,sample TEXT,source TEXT,report TEXT)')
            conn.execute('INSERT INTO runs VALUES(?,?,?,?,?)',('test-run',test.report['timestamp'],'Test specimen','Test data',json.dumps(test.report)))
        app = AppTest.from_file(str(ROOT/'app.py'),default_timeout=180).run()
        self.assertFalse(app.exception,str(app.exception))
        self.assertIn('Evidence notebook',[tab.label for tab in app.tabs])
        app.text_input(key='case_title').set_value('UI case')
        next(b for b in app.button if b.label=='Create notebook').click().run()
        self.assertFalse(app.exception,str(app.exception))
        case_id = app.session_state['case_selected']
        next(b for b in app.button if b.label=='Link analysis snapshot').click().run()
        self.assertFalse(app.exception,str(app.exception))
        app.text_area(key=f'peak_note_text_{case_id}').set_value('Inspect the peak at 82')
        next(b for b in app.button if b.label=='Save peak annotation').click().run()
        self.assertFalse(app.exception,str(app.exception))
        app.text_area(key=f'review_conflicts_{case_id}').set_value('Need independent evidence')
        next(b for b in app.button if b.label=='Save review notes').click().run()
        self.assertFalse(app.exception,str(app.exception))
        bundle = NotebookStore(directory/'notebooks').bundle(case_id)
        self.assertEqual(len(bundle['analyses']),1)
        self.assertEqual(len(bundle['annotations']),1)
        self.assertEqual(bundle['case']['conflicts'],'Need independent evidence')
        next(b for b in app.button if b.label=='Prepare case export').click().run()
        self.assertFalse(app.exception,str(app.exception))
        self.assertIn(f'notebook_export_{case_id}',app.session_state)


if __name__ == '__main__':
    unittest.main()
