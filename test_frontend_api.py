"""Exercise all backend feature routes with isolated records and real reference data."""
from pathlib import Path
from threading import Thread
import base64
import csv
import io
import json
import os
import sys
import unittest
import urllib.request
import urllib.error
import uuid
import zipfile
from unittest.mock import patch

HERE=Path(__file__).parent
DATA=HERE if (HERE/'swgdrug_library.csv').exists() else HERE.parent.parent
os.environ['FORENSIC_STORAGE_DIR']=str(DATA/'__pycache__'/'web_tests'/uuid.uuid4().hex)
sys.path.insert(0,str(HERE))
import server


class FrontendAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.base=f'http://127.0.0.1:{cls.http.server_port}'
        cls.thread=Thread(target=cls.http.serve_forever,daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close()

    def request(self,path,data=None):
        request=urllib.request.Request(self.base+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=60) as response:
            return json.load(response)

    def test_library_and_results(self):
        self.assertEqual(self.request('/api/status')['references'],3826)
        self.assertEqual(len(self.request('/api/library')),3826)
        spectrum=self.request('/api/spectrum/1747')
        self.assertEqual(spectrum['entry']['name'],'Cocaine')
        self.assertEqual(len(spectrum['vector']),541)
        report=self.request('/api/analyze',{'mode':'reference','entry_id':1747})
        holdout=report['reference_holdout']
        self.assertEqual(report['source'],'Reference holdout check')
        self.assertEqual(holdout['selected_entry_id'],1747)
        self.assertIn(1747,holdout['excluded_entry_ids'])
        self.assertNotIn(report['best_entry_id'],holdout['excluded_entry_ids'])
        self.assertNotIn(1747,report['exact_match_entry_ids'])
        self.assertLess(report['cosine_similarity'],1)
        self.assertGreater(report['rmse'],0)
        second=self.request('/api/analyze',{'mode':'reference','entry_id':1110})
        self.assertNotEqual(report['cosine_similarity'],second['cosine_similarity'])
        self.assertNotEqual(report['rmse'],second['rmse'])
        restored=self.request('/api/history/'+report['run_id'])
        self.assertEqual(restored,report)
        self.assertTrue(self.request('/api/history'))
        with urllib.request.urlopen(self.base+'/api/history/'+report['run_id']+'/export?format=csv') as response:
            self.assertIn('text/csv',response.headers['Content-Type'])
            exported=response.read().decode('utf-8-sig')
        table=csv.DictReader(io.StringIO(exported))
        self.assertEqual(table.fieldnames,['Sample','Analysis method','Closest library match','Match entry ID',
                         'Match formula','Match mass (Da)','Cosine similarity','Fit R-squared','Fit RMSE',
                         'Residual/input (%)','m/z (nominal mass)','Input intensity (%)',
                         'Reconstructed intensity (%)','Residual intensity (percentage points)'])
        rows=list(table)
        self.assertEqual(len(rows),541)
        self.assertEqual(rows[0]['Sample'],'Cocaine')
        self.assertEqual(rows[0]['Analysis method'],'Reference holdout check')
        self.assertEqual(rows[0]['Closest library match'],report['best_name'])
        self.assertEqual(rows[0]['m/z (nominal mass)'],'10')

    def test_mixture_and_sweep(self):
        body={'entry_ids':[1747,1110],'shares':[70,30],'noise':0,'loss':0,'extra':0,'seed':42,'mode':'analyze'}
        result=self.request('/api/simulate',body)
        recovered={c['entry_id']:c['fit_weight_percent'] for c in result['report']['components']}
        self.assertAlmostEqual(recovered[1747],70,places=4)
        body['mode']='sweep'
        sweep=self.request('/api/simulate',body)
        self.assertEqual(len(sweep['rows']),11)
        self.assertLess(max(r['A_absolute_error_pp'] for r in sweep['rows']),1e-7)

    def test_upload_batch_and_rejection(self):
        file={'name':'test.csv','data':base64.b64encode(b'mz,intensity\n82,100\n182,75\n').decode()}
        self.assertEqual(self.request('/api/parse',file)[0]['peak_count'],2)
        report=self.request('/api/analyze',{'mode':'file','file':file,'record':0})
        self.assertEqual(report['peak_count'],2)
        batch=self.request('/api/batch',{'files':[file,{'name':'invalid.csv','data':base64.b64encode(b'82,-100').decode()}]})
        self.assertEqual(len(batch['reports']),1)
        self.assertEqual(len(batch['errors']),1)
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/analyze',{'mode':'text','text':'82:-1'})
        self.assertEqual(error.exception.code,400)

    def test_notebook_workflow_and_export(self):
        report=self.request('/api/analyze',{'mode':'reference','entry_id':1110})
        case=self.request('/api/notebooks',{'title':'Frontend test case','sample':'Test specimen','analyst':'Test analyst'})['id']
        path='/api/notebooks/'+case
        self.request(path+'/link',{'run_id':report['run_id']})
        self.request(path+'/annotate',{'run_id':report['run_id'],'mz':194,'position':'Unresolved observation','note':'Review ion'})
        self.request(path+'/update',{'analyst':'Reviewer','status':'Awaiting review','interpretation':'Tentative only','conflicts':'Independent evidence needed'})
        payload=b'evidence data'
        self.request(path+'/attach',{'file':{'name':'ftir.txt','data':base64.b64encode(payload).decode()},'kind':'FTIR evidence','notes':'Supporting file'})
        bundle=self.request(path)
        self.assertEqual(len(bundle['analyses']),1)
        self.assertEqual(len(bundle['annotations']),1)
        self.assertEqual(bundle['case']['status'],'Awaiting review')
        with urllib.request.urlopen(self.base+path+'/export?format=zip') as response:
            with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
                self.assertIn('report.html',archive.namelist())
                self.assertIn('case.json',archive.namelist())
                self.assertIn(payload,[archive.read(name) for name in archive.namelist() if name.startswith('attachments/')])

    def test_cross_origin_mutation_rejected(self):
        request=urllib.request.Request(self.base+'/api/notebooks',data=b'{}',headers={'Content-Type':'application/json','Origin':'https://unrelated.example'})
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        self.assertEqual(error.exception.code,403)

    def test_deployed_frontend_cors(self):
        origin = 'https://forensic-demo.vercel.app'
        with patch.dict(os.environ, {'FORENSIC_ALLOWED_ORIGINS': origin}):
            request = urllib.request.Request(self.base+'/api/status', method='OPTIONS',
                headers={'Origin': origin, 'Access-Control-Request-Method': 'POST',
                         'Access-Control-Request-Headers': 'content-type'})
            with urllib.request.urlopen(request) as response:
                self.assertEqual(response.status, 204)
                self.assertEqual(response.headers['Access-Control-Allow-Origin'], origin)
                self.assertIn('POST', response.headers['Access-Control-Allow-Methods'])
            request = urllib.request.Request(self.base+'/api/notebooks',
                data=json.dumps({'title': 'Cross-origin deployment test'}).encode(),
                headers={'Content-Type': 'application/json', 'Origin': origin})
            with urllib.request.urlopen(request) as response:
                case_id = json.load(response)['id']
                self.assertEqual(response.headers['Access-Control-Allow-Origin'], origin)
            request = urllib.request.Request(self.base+'/api/notebooks/'+case_id+'/export?format=json',
                headers={'Origin': origin})
            with urllib.request.urlopen(request) as response:
                self.assertEqual(response.headers['Access-Control-Allow-Origin'], origin)
                self.assertIn('attachment', response.headers['Content-Disposition'])
            for forbidden in ['https://unrelated.example', origin+'.evil.example']:
                request = urllib.request.Request(self.base+'/api/status', method='OPTIONS',
                    headers={'Origin': forbidden})
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(request)
                self.assertEqual(error.exception.code, 403)
                self.assertIsNone(error.exception.headers.get('Access-Control-Allow-Origin'))


if __name__=='__main__':
    unittest.main()
