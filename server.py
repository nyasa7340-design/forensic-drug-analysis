"""Local same-origin API and static frontend for the existing validated analysis engines.

Run: python server.py --port 8503. The listener is deliberately bound to localhost.
"""
from contextlib import contextmanager
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import argparse
import base64
import csv
import hashlib
import io
import json
import os
import sqlite3
import sys
import uuid

import numpy as np

ROOT = Path(__file__).resolve().parent
DATA = ROOT if (ROOT / 'swgdrug_library.csv').exists() else ROOT.parent.parent
sys.path.insert(0, str(DATA))
from analysis_core import load_library, analyze, parse_spectra, MZ
from simulation_core import simulate_signals, fingerprint_diagnostics, ratio_sweep
from evidence_notebook import NotebookStore, now

LIBRARY, MATRIX = load_library(DATA)
DIGEST = hashlib.sha256((DATA / 'swgdrug_features.csv').read_bytes()).hexdigest()
BY_ID = {int(row.id): i for i, row in LIBRARY.iterrows()}
try:
    STORAGE = Path(os.environ.get('FORENSIC_STORAGE_DIR', str(DATA / '__pycache__')))
    STORAGE.mkdir(parents=True, exist_ok=True)
except OSError:
    if os.environ.get('FORENSIC_STORAGE_DIR'):
        raise
    STORAGE = Path(os.environ.get('TEMP', '/tmp')) / 'forensic_storage'
    STORAGE.mkdir(parents=True, exist_ok=True)
NOTEBOOKS = NotebookStore(STORAGE / 'evidence_notebooks')


@contextmanager
def history_connection():
    conn = sqlite3.connect(STORAGE / 'analysis_history.sqlite3', timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            conn.execute('CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,timestamp TEXT,sample TEXT,source TEXT,report TEXT)')
            yield conn
    finally:
        conn.close()


def history_report(run_id):
    with history_connection() as conn:
        row = conn.execute('SELECT report FROM runs WHERE id=?', (run_id,)).fetchone()
    if row is None:
        raise ValueError('Saved analysis not found.')
    return json.loads(row['report'])


def run_analysis(vector, sample, source, simulation=None, settings=None, excluded=0,
                 exclude_entry_ids=None, reference_holdout=None):
    report = analyze(vector, LIBRARY, MATRIX, exclude_entry_ids=exclude_entry_ids)
    report.update(run_id=uuid.uuid4().hex, timestamp=now(), sample=str(sample)[:150], source=source,
                  simulation=simulation, simulation_settings=settings, excluded_peak_count=excluded,
                  reference_holdout=reference_holdout,
                  library_version='SWGDRUG 3.14 (bundled)', library_sha256=DIGEST,
                  interpretation='Screening comparison. Fit weights are spectral coefficients, not concentration or purity. Similarity is not an identity probability.')
    with history_connection() as conn:
        conn.execute('INSERT INTO runs VALUES(?,?,?,?,?)', (report['run_id'], report['timestamp'], report['sample'],source,json.dumps(report,allow_nan=False)))
    return report


def records_from_upload(upload):
    try:
        payload = base64.b64decode(upload['data'], validate=True)
    except (ValueError,KeyError) as exc:
        raise ValueError('Invalid file encoding.') from exc
    if len(payload) > 20 * 1024 * 1024:
        raise ValueError('Spectrum files must be no larger than 20 MB.')
    return parse_spectra(payload,str(upload.get('name','Uploaded spectrum')))


class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(ROOT/'frontend'),**kwargs)

    def log_message(self, format, *args):
        # Keep routine requests out of the terminal; unexpected HTTP errors remain visible.
        if args and str(args[1] if len(args)>1 else '').startswith('5'):
            super().log_message(format,*args)

    def origin_allowed(self):
        origin = self.headers.get('Origin')
        if not origin:
            return True
        allowed = {value.strip().rstrip('/') for value in
                   os.environ.get('FORENSIC_ALLOWED_ORIGINS', '').split(',') if value.strip()}
        parsed = urlparse(origin)
        return (origin in allowed or
                (parsed.scheme in {'http', 'https'} and parsed.netloc == self.headers.get('Host')))

    def end_headers(self):
        origin = self.headers.get('Origin')
        if origin and self.origin_allowed():
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        super().end_headers()

    def do_OPTIONS(self):
        if not self.path.startswith('/api/'):
            return self.send_json({'error': 'Endpoint not found.'}, 404)
        if not self.origin_allowed():
            return self.send_json({'error': 'Website origin is not allowed.'}, 403)
        self.send_response(204)
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Max-Age', '600')
        self.send_header('Content-Length', '0')
        self.end_headers()

    def send_bytes(self, payload, content_type, filename=None, status=200):
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(payload)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','same-origin')
        self.send_header('Cache-Control','no-store' if self.path.startswith('/api/') else 'no-cache')
        if filename:
            self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self,data,status=200):
        self.send_bytes(json.dumps(data,allow_nan=False).encode(),'application/json; charset=utf-8',status=status)

    def do_GET(self):
        url = urlparse(self.path)
        parts = url.path.strip('/').split('/')
        query = parse_qs(url.query)
        if parts[0] != 'api':
            return super().do_GET()
        try:
            if parts == ['api','status']:
                with history_connection() as conn:
                    count = conn.execute('SELECT count(*) FROM runs').fetchone()[0]
                return self.send_json({'references':len(LIBRARY),'channels':541,'saved_analyses':count,'notebooks':len(NOTEBOOKS.cases()),'library_version':'SWGDRUG 3.14','library_sha256':DIGEST})
            if parts == ['api','library']:
                return self.send_json(LIBRARY[['id','name','formula','mw','base_peak_mz','num_peaks']].to_dict('records'))
            if len(parts)==3 and parts[:2]==['api','spectrum']:
                index = BY_ID[int(parts[2])]
                return self.send_json({'entry':LIBRARY.iloc[index][['id','name','formula','mw','base_peak_mz','num_peaks']].to_dict(),'vector':MATRIX[index].tolist()})
            if parts == ['api','history']:
                with history_connection() as conn:
                    rows = conn.execute('SELECT * FROM runs ORDER BY timestamp DESC LIMIT 500').fetchall()
                return self.send_json([{k:row[k] for k in ['id','timestamp','sample','source']} | {'best_name':json.loads(row['report'])['best_name']} for row in rows])
            if len(parts)>=3 and parts[:2]==['api','history']:
                report = history_report(parts[2])
                if len(parts)==4 and parts[3]=='export':
                    if query.get('format',['json'])[0]=='csv':
                        stream = io.StringIO(newline='')
                        writer = csv.writer(stream)
                        best = next((match for match in report['matches']
                                     if int(match['entry_id']) == int(report['best_entry_id'])), {})
                        columns = ['Sample', 'Analysis method', 'Closest library match', 'Match entry ID',
                                   'Match formula', 'Match mass (Da)', 'Cosine similarity', 'Fit R-squared',
                                   'Fit RMSE', 'Residual/input (%)', 'm/z (nominal mass)',
                                   'Input intensity (%)', 'Reconstructed intensity (%)',
                                   'Residual intensity (percentage points)']
                        writer.writerow(columns)
                        summary = [report['sample'], report['source'], report['best_name'],
                                   report['best_entry_id'], best.get('formula', ''), best.get('mw', ''),
                                   round(report['cosine_similarity'], 6),
                                   round(report['r_squared'], 6) if report['r_squared'] is not None else '',
                                   round(report['rmse'], 6), round(report['relative_residual'] * 100, 4)]
                        writer.writerows([*summary, int(mz), round(float(input_value), 6),
                                          round(float(fit_value), 6), round(float(residual_value), 6)]
                                         for mz, input_value, fit_value, residual_value in
                                         zip(MZ, report['query'], report['reconstructed'], report['residual']))
                        return self.send_bytes(stream.getvalue().encode('utf-8-sig'),'text/csv; charset=utf-8',f'spectrum-{parts[2][:8]}.csv')
                    return self.send_bytes(json.dumps(report,indent=2).encode(),'application/json',f'analysis-{parts[2][:8]}.json')
                return self.send_json(report)
            if parts == ['api','notebooks']:
                return self.send_json(NOTEBOOKS.cases())
            if len(parts)>=3 and parts[:2]==['api','notebooks']:
                case_id=parts[2]
                if len(parts)==4 and parts[3]=='export':
                    package,html,content=NOTEBOOKS.export(case_id)
                    format=query.get('format',['zip'])[0]
                    payload,mime = (html.encode(),'text/html') if format=='html' else ((content.encode(),'application/json') if format=='json' else (package,'application/zip'))
                    return self.send_bytes(payload,mime,f'case-{case_id[:12]}.{format if format in ["html","json"] else "zip"}')
                if len(parts)==5 and parts[3]=='attachments':
                    attachment=NOTEBOOKS.attachment(case_id,parts[4])
                    # Original name is metadata; the download header uses a safe generated name.
                    return self.send_bytes(attachment['payload'],'application/octet-stream',f'evidence-{attachment["id"][:12]}{Path(attachment["name"]).suffix}')
                return self.send_json(NOTEBOOKS.bundle(case_id))
            self.send_json({'error':'Endpoint not found.'},404)
        except (ValueError,KeyError,IndexError) as exc:
            self.send_json({'error':str(exc)},400)
        except Exception:
            self.send_json({'error':'The server could not complete this request.'},500)

    def do_POST(self):
        try:
            origin=self.headers.get('Origin')
            if not self.origin_allowed():
                return self.send_json({'error':'Website origin is not allowed.'},403)
            if not self.headers.get('Content-Type','').startswith('application/json'):
                return self.send_json({'error':'Requests must use application/json.'},415)
            length=int(self.headers.get('Content-Length','0'))
            if not 0 < length <= 30*1024*1024:
                return self.send_json({'error':'Request must be no larger than 30 MB.'},413)
            body=json.loads(self.rfile.read(length))
            parts=urlparse(self.path).path.strip('/').split('/')
            if parts==['api','parse']:
                records=records_from_upload(body)
                return self.send_json([{'name':r.name,'peak_count':r.peak_count,'excluded_peak_count':r.excluded_peak_count} for r in records])
            if parts==['api','analyze']:
                mode=body.get('mode')
                if mode=='reference':
                    index=BY_ID[int(body['entry_id'])]
                    selected=LIBRARY.iloc[index]
                    identical=np.flatnonzero(np.all(np.isclose(MATRIX, MATRIX[index], atol=1e-8, rtol=0), axis=1))
                    excluded_ids=LIBRARY.iloc[identical]['id'].astype(int).tolist()
                    holdout={'selected_entry_id':int(selected['id']), 'selected_name':str(selected['name']),
                             'excluded_entry_ids':excluded_ids}
                    return self.send_json(run_analysis(MATRIX[index],str(selected['name']),'Reference holdout check',
                                                       exclude_entry_ids=excluded_ids,reference_holdout=holdout))
                if mode=='text':
                    record=parse_spectra(body['text'],str(body.get('name','Measured spectrum')))[0]
                    return self.send_json(run_analysis(record.vector,record.name,'Manual peak list'))
                if mode=='file':
                    record=records_from_upload(body['file'])[int(body.get('record',0))]
                    return self.send_json(run_analysis(record.vector,record.name,'Upload: '+body['file']['name'],excluded=record.excluded_peak_count))
                raise ValueError('Choose a supported input method.')
            if parts==['api','simulate']:
                ids=[int(i) for i in body['entry_ids']]
                if not 2<=len(ids)<=3 or len(set(ids))!=len(ids):
                    raise ValueError('Select two or three different reference entries.')
                spectra=MATRIX[[BY_ID[i] for i in ids]]
                names=[str(LIBRARY.iloc[BY_ID[i]]['name']) for i in ids]
                shares=[float(s) for s in body['shares']]
                settings=[float(body.get('noise',0)),float(body.get('loss',0)),int(body.get('extra',0)),int(body.get('seed',42))]
                experiment=simulate_signals(spectra,shares,*settings)
                diagnostics=fingerprint_diagnostics(spectra,names)
                truth=[{'entry_id':id,'name':name,'input_coefficient_percent':share} for id,name,share in zip(ids,names,shares)]
                mode=body.get('mode','preview')
                if mode=='sweep':
                    return self.send_json({'rows':ratio_sweep(spectra,names,*settings),'references':names[:2],'settings':experiment['settings']})
                if mode=='analyze':
                    report=run_analysis(experiment['observed'],'Synthetic challenge: '+' + '.join(f'{s:g}% {n}' for s,n in zip(shares,names)),'Synthetic signal mixture',truth,{'experiment':experiment,'fingerprint_diagnostics':diagnostics})
                    return self.send_json({'report':report,'experiment':experiment,'diagnostics':diagnostics,'truth':truth})
                return self.send_json({'experiment':experiment,'diagnostics':diagnostics,'truth':truth})
            if parts==['api','batch']:
                records,errors=[],[]
                for file in body['files']:
                    try:
                        records.extend((r,file['name']) for r in records_from_upload(file))
                    except ValueError as exc:
                        errors.append({'file':file['name'],'error':str(exc)})
                if len(records)>50:
                    raise ValueError('A batch may contain at most 50 spectra. No results were saved.')
                reports=[run_analysis(r.vector,r.name,'Batch upload: '+name,excluded=r.excluded_peak_count) for r,name in records]
                return self.send_json({'reports':reports,'errors':errors})
            if parts==['api','notebooks']:
                return self.send_json({'id':NOTEBOOKS.create(body['title'],body.get('sample',''),body.get('analyst',''))})
            if len(parts)==4 and parts[:2]==['api','notebooks']:
                case_id,action=parts[2:]
                if action=='update':
                    NOTEBOOKS.update(case_id,body.get('analyst',''),body['status'],body.get('interpretation',''),body.get('conflicts',''))
                elif action=='link':
                    NOTEBOOKS.link(case_id,history_report(body['run_id']))
                elif action=='attach':
                    NOTEBOOKS.attach(case_id,body['file']['name'],base64.b64decode(body['file']['data'],validate=True),body['kind'],body.get('notes',''))
                elif action=='annotate':
                    NOTEBOOKS.annotate(case_id,body['run_id'],int(body['mz']),body['position'],body['note'])
                else:
                    raise ValueError('Unknown notebook action.')
                return self.send_json(NOTEBOOKS.bundle(case_id))
            self.send_json({'error':'Endpoint not found.'},404)
        except (ValueError,KeyError,IndexError,TypeError) as exc:
            self.send_json({'error':str(exc)},400)
        except Exception:
            self.send_json({'error':'The server could not complete this request.'},500)


handler = Handler
app = Handler
application = Handler


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=int(os.environ.get('PORT', '8503')))
    parser.add_argument('--host',default=os.environ.get('HOST', '127.0.0.1'))
    args=parser.parse_args()
    with ThreadingHTTPServer((args.host,args.port),Handler) as server:
        print(f'forensic-drug-analysis running at http://{args.host}:{args.port}',flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
