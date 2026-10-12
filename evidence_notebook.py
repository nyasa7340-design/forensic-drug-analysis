"""Local evidence notebooks with immutable analysis snapshots and portable exports."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from html import escape
from pathlib import Path
import hashlib
import io
import json
import sqlite3
import uuid
import zipfile

KINDS = ['Chromatogram', 'FTIR evidence', 'Instrument report', 'Reference documentation', 'Other supporting evidence']
STATUSES = ['Draft', 'Awaiting review', 'Reviewed']
POSITIONS = ['Supports interpretation', 'Conflicts with interpretation', 'Unresolved observation']
EXTENSIONS = {'.pdf', '.png', '.jpg', '.jpeg', '.csv', '.txt', '.jdx', '.dx'}


def now():
    return datetime.now(timezone(timedelta(hours=5, minutes=30))).isoformat(timespec='seconds')


class NotebookStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript('''
            CREATE TABLE IF NOT EXISTS cases(id TEXT PRIMARY KEY,title TEXT NOT NULL,sample TEXT,analyst TEXT,status TEXT,interpretation TEXT,conflicts TEXT,created TEXT,updated TEXT);
            CREATE TABLE IF NOT EXISTS attachments(id TEXT PRIMARY KEY,case_id TEXT,kind TEXT,name TEXT,sha256 TEXT,payload BLOB,notes TEXT,created TEXT);
            CREATE TABLE IF NOT EXISTS snapshots(case_id TEXT,run_id TEXT,report TEXT,created TEXT,PRIMARY KEY(case_id,run_id));
            CREATE TABLE IF NOT EXISTS annotations(id TEXT PRIMARY KEY,case_id TEXT,run_id TEXT,mz INTEGER,position TEXT,note TEXT,created TEXT);
            CREATE TABLE IF NOT EXISTS activity(id INTEGER PRIMARY KEY AUTOINCREMENT,case_id TEXT,action TEXT,details TEXT,created TEXT);
            ''')

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.directory / 'notebooks.sqlite3', timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def event(self, conn, case_id, action, details):
        conn.execute('INSERT INTO activity(case_id,action,details,created) VALUES(?,?,?,?)', (case_id, action, details, now()))

    def create(self, title, sample='', analyst=''):
        if not title.strip():
            raise ValueError('Enter a case title.')
        case_id = uuid.uuid4().hex
        stamp = now()
        with self.connect() as conn:
            conn.execute('INSERT INTO cases VALUES(?,?,?,?,?,?,?,?,?)', (case_id,title.strip(),sample.strip(),analyst.strip(),'Draft','','',stamp,stamp))
            self.event(conn, case_id, 'Case created', title.strip())
        return case_id

    def cases(self):
        with self.connect() as conn:
            return [dict(row) for row in conn.execute('SELECT * FROM cases ORDER BY updated DESC,id')]

    def require_case(self, conn, case_id):
        if conn.execute('SELECT id FROM cases WHERE id=?', (case_id,)).fetchone() is None:
            raise ValueError('This notebook does not exist.')

    def update(self, case_id, analyst, status, interpretation, conflicts):
        if status not in STATUSES:
            raise ValueError('Unknown review status.')
        with self.connect() as conn:
            self.require_case(conn, case_id)
            conn.execute('UPDATE cases SET analyst=?,status=?,interpretation=?,conflicts=?,updated=? WHERE id=?', (analyst.strip(),status,interpretation.strip(),conflicts.strip(),now(),case_id))
            self.event(conn, case_id, 'Review notes saved', f'Status: {status}; entered reviewer: {analyst.strip() or "unspecified"}')

    def link(self, case_id, report):
        run_id = str(report['run_id'])
        payload = json.dumps(report, allow_nan=False)
        with self.connect() as conn:
            self.require_case(conn, case_id)
            cursor = conn.execute('INSERT OR IGNORE INTO snapshots VALUES(?,?,?,?)', (case_id,run_id,payload,now()))
            if cursor.rowcount:
                self.event(conn, case_id, 'Analysis linked', f'{run_id}: {report.get("sample", "Unnamed analysis")}')
            return bool(cursor.rowcount)

    def attach(self, case_id, filename, payload, kind, notes):
        # Store original bytes in SQLite; never execute files or write user-supplied paths.
        name = Path(filename.replace('\\', '/')).name
        if Path(name).suffix.lower() not in EXTENSIONS:
            raise ValueError('Unsupported attachment type.')
        if not payload or len(payload) > 20 * 1024 * 1024:
            raise ValueError('Attachments must contain data and be no larger than 20 MB.')
        if kind not in KINDS:
            raise ValueError('Choose an evidence type.')
        digest = hashlib.sha256(payload).hexdigest()
        with self.connect() as conn:
            self.require_case(conn, case_id)
            existing = conn.execute('SELECT id FROM attachments WHERE case_id=? AND sha256=?', (case_id,digest)).fetchone()
            if existing:
                raise ValueError('This exact attachment is already saved in the notebook.')
            attachment_id = uuid.uuid4().hex
            conn.execute('INSERT INTO attachments VALUES(?,?,?,?,?,?,?,?)', (attachment_id,case_id,kind,name,digest,payload,notes.strip(),now()))
            self.event(conn, case_id, 'Evidence attached', f'{kind}: {name}; SHA-256 {digest}')
        return attachment_id

    def annotate(self, case_id, run_id, mz, position, note):
        if not 10 <= int(mz) <= 550 or position not in POSITIONS or not note.strip():
            raise ValueError('Choose m/z 10–550, an observation type, and enter a note.')
        with self.connect() as conn:
            self.require_case(conn, case_id)
            if conn.execute('SELECT run_id FROM snapshots WHERE case_id=? AND run_id=?', (case_id,run_id)).fetchone() is None:
                raise ValueError('Link this analysis before annotating it.')
            conn.execute('INSERT INTO annotations VALUES(?,?,?,?,?,?,?)', (uuid.uuid4().hex,case_id,run_id,int(mz),position,note.strip(),now()))
            self.event(conn, case_id, 'Peak annotated', f'{run_id}; m/z {mz}; {position}')

    def bundle(self, case_id):
        with self.connect() as conn:
            self.require_case(conn, case_id)
            case = dict(conn.execute('SELECT * FROM cases WHERE id=?', (case_id,)).fetchone())
            snapshots = [{'report': json.loads(row['report']), 'linked_at': row['created']} for row in conn.execute('SELECT * FROM snapshots WHERE case_id=? ORDER BY created,run_id', (case_id,))]
            attachments = [dict(row) for row in conn.execute('SELECT id,kind,name,sha256,notes,created,length(payload) AS size_bytes FROM attachments WHERE case_id=? ORDER BY created,id', (case_id,))]
            annotations = [dict(row) for row in conn.execute('SELECT * FROM annotations WHERE case_id=? ORDER BY created,id', (case_id,))]
            activity = [dict(row) for row in conn.execute('SELECT action,details,created FROM activity WHERE case_id=? ORDER BY id', (case_id,))]
        return {'case': case, 'analyses': snapshots, 'attachments': attachments, 'annotations': annotations, 'activity': activity,
                'limitations': 'Screening evidence and analyst-entered notes. Review status is self-declared; this local activity log is not a tamper-proof chain of custody. Attachments are not automatically interpreted or used to confirm identity.'}

    def attachment(self, case_id, attachment_id):
        with self.connect() as conn:
            row = conn.execute('SELECT * FROM attachments WHERE case_id=? AND id=?', (case_id,attachment_id)).fetchone()
        if row is None:
            raise ValueError('Attachment not found in this notebook.')
        record = dict(row)
        if hashlib.sha256(record['payload']).hexdigest() != record['sha256']:
            raise ValueError('Attachment checksum does not match its saved record.')
        return record

    def export(self, case_id):
        bundle = self.bundle(case_id)
        content = json.dumps(bundle, indent=2, allow_nan=False)
        case = bundle['case']

        def table(rows, columns):
            if not rows:
                return '<p class="muted">No entries recorded.</p>'
            return '<table><thead><tr>' + ''.join(f'<th>{escape(c.replace("_", " "))}</th>' for c in columns) + '</tr></thead><tbody>' + ''.join('<tr>' + ''.join(f'<td>{escape(str(row.get(c,"")))}</td>' for c in columns) + '</tr>' for row in rows) + '</tbody></table>'

        analysis_rows = [{**record['report'], 'linked_at': record['linked_at']} for record in bundle['analyses']]
        html = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Evidence notebook</title><style>body{max-width:1100px;margin:40px auto;padding:24px;font:15px/1.6 system-ui;color:#24302f;background:#f5f4ef}h1,h2{font-weight:550}section{background:white;padding:20px;border:1px solid #dde3df;border-radius:8px;margin:18px 0}table{width:100%;border-collapse:collapse;font-size:12px;table-layout:fixed}td,th{text-align:left;padding:8px;border-bottom:1px solid #ddd;overflow-wrap:anywhere}p{white-space:pre-wrap}.muted{color:#596967}@media print{body{margin:0;background:white}section{break-inside:avoid}}</style>'''
        html += f'<h1>{escape(case["title"])}</h1><p>Case ID: {escape(case["id"])}\nSample: {escape(case["sample"])}\nEntered analyst: {escape(case["analyst"] or "Not recorded")}\nReview status: {escape(case["status"])}\nCreated: {escape(case["created"])}\nLast notes update: {escape(case["updated"])}</p>'
        for title, text in [('Working interpretation',case['interpretation']), ('Conflicting evidence and open questions',case['conflicts'])]:
            html += f'<section><h2>{title}</h2><p>{escape(text or "Not recorded.")}</p></section>'
        for title, rows, columns in [('Linked analyses',analysis_rows,['run_id','sample','source','status','best_name','cosine_similarity','rmse','library_sha256']), ('Supporting evidence',bundle['attachments'],['kind','name','notes','sha256']), ('Peak annotations',bundle['annotations'],['run_id','mz','position','note','created']), ('Activity log',bundle['activity'],['created','action','details'])]:
            html += f'<section><h2>{title}</h2>{table(rows,columns)}</section>'
        html += f'<section><h2>Interpretation limits</h2><p>{escape(bundle["limitations"])}</p><p>Cosine similarity is not an identity probability. Spectral fit weights are not calibrated concentrations or purity measurements. Full analysis vectors and metadata are included in case.json.</p></section></html>'
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('report.html', html)
            archive.writestr('case.json', content)
            for item in bundle['attachments']:
                record = self.attachment(case_id, item['id'])
                # IDs and supported extensions produce safe unique ZIP paths.
                archive.writestr(f'attachments/{item["id"]}{Path(item["name"]).suffix.lower()}',record['payload'])
        return output.getvalue(), html, content


def render_notebook(directory, saved_runs, analysis_connection):
    import pandas as pd
    import streamlit as st

    store = NotebookStore(directory)
    st.subheader('Evidence notebook')
    st.caption('Keep analyses, supporting files, and review notes together. Notebooks are saved on this computer across restarts.')
    with st.expander('Create a notebook', expanded=not store.cases()):
        with st.form('case_create'):
            title = st.text_input('Case title', max_chars=150, key='case_title')
            sample = st.text_input('Sample or exhibit reference', max_chars=150, key='case_sample')
            analyst = st.text_input('Analyst name (optional)', max_chars=150, key='case_analyst_new')
            create = st.form_submit_button('Create notebook', type='primary')
        if create:
            try:
                st.session_state.case_selected = store.create(title,sample,analyst)
                st.success('Notebook created.')
            except ValueError as exc:
                st.error(str(exc))
    cases = store.cases()
    if not cases:
        st.info('Create a notebook, then link saved analyses and attach supporting evidence.')
        return
    lookup = {row['id']: row for row in cases}
    case_id = st.selectbox('Open notebook', list(lookup), format_func=lambda id: f'{lookup[id]["title"]} · {lookup[id]["status"]}', key='case_selected')
    bundle = store.bundle(case_id)
    case = bundle['case']
    count_boxes = [column.empty() for column in st.columns(3)]
    for box,label,key in zip(count_boxes,['Linked analyses','Evidence files','Peak annotations'],['analyses','attachments','annotations']):
        box.metric(label,len(bundle[key]))
    st.caption(f'Case {case_id[:12]} · Sample: {case["sample"] or "not recorded"} · Created {case["created"]}')
    linking, files, peaks, review, export = st.tabs(['Linked analyses','Supporting evidence','Peak annotations','Review notes','Report & activity'])
    with linking:
        if saved_runs.empty:
            st.info('Run and save a spectrum analysis first.')
        else:
            run_lookup = saved_runs.set_index('id')
            run_id = st.selectbox('Saved analysis to link', saved_runs.id.tolist(), format_func=lambda id: f'{run_lookup.loc[id,"timestamp"]} · {run_lookup.loc[id,"sample"]}', key=f'case_link_{case_id}')
            if st.button('Link analysis snapshot', key=f'case_link_button_{case_id}', type='primary'):
                with analysis_connection() as conn:
                    row = conn.execute('SELECT report FROM runs WHERE id=?', (run_id,)).fetchone()
                if row is not None:
                    added = store.link(case_id,json.loads(row[0]))
                    st.success('Analysis linked as a saved snapshot.' if added else 'This analysis is already linked.')
                    bundle = store.bundle(case_id)
            st.caption('The original input, results, library checksum, and simulation settings are copied into the notebook. Later analyses do not replace the snapshot.')
        if bundle['analyses']:
            st.dataframe(pd.DataFrame([{k:r['report'].get(k) for k in ['sample','timestamp','source','best_name','cosine_similarity']} for r in bundle['analyses']]), hide_index=True,width='stretch')
    with files:
        st.caption('Attach chromatograms, FTIR evidence, or reference documentation. These files support manual review; uploading them does not alter the calculated spectral result.')
        with st.form(f'evidence_upload_{case_id}'):
            kind = st.selectbox('Evidence type',KINDS,key=f'evidence_kind_{case_id}')
            upload = st.file_uploader('Evidence file · maximum 20 MB',type=['pdf','png','jpg','jpeg','csv','txt','jdx','dx'],key=f'evidence_file_{case_id}')
            notes = st.text_area('Evidence description or observation',key=f'evidence_notes_{case_id}')
            attach = st.form_submit_button('Save evidence',type='primary')
        if attach:
            try:
                if upload is None:
                    raise ValueError('Select an evidence file.')
                store.attach(case_id,upload.name,upload.getvalue(),kind,notes)
                st.success('Evidence saved with its SHA-256 checksum.')
                bundle = store.bundle(case_id)
            except ValueError as exc:
                st.error(str(exc))
        for item in bundle['attachments']:
            with st.expander(f'{item["kind"]} · {item["name"]}'):
                st.write(item['notes'] or 'No description recorded.')
                st.caption(f'{item["size_bytes"]:,} bytes · {item["created"]} · SHA-256 {item["sha256"]}')
                try:
                    record = store.attachment(case_id,item['id'])
                    st.download_button('Download original file',record['payload'],item['name'],key=f'evidence_download_{item["id"]}')
                except ValueError as exc:
                    st.error(str(exc))
    with peaks:
        if not bundle['analyses']:
            st.info('Link an analysis before adding peak observations.')
        else:
            reports = {r['report']['run_id']:r['report'] for r in bundle['analyses']}
            run_id = st.selectbox('Analysis for annotation',list(reports),format_func=lambda id: f'{reports[id]["sample"]} · {id[:8]}',key=f'peak_report_{case_id}')
            mz = int(st.number_input('Peak m/z',10,550,82,key=f'peak_mz_{case_id}'))
            report = reports[run_id]
            position = mz-10
            a,b,c = st.columns(3)
            for col,key,title in [(a,'query','Input intensity'),(b,'reconstructed','Fitted intensity'),(c,'residual','Residual intensity')]:
                col.metric(title,f'{report[key][position]:.3f}')
            with st.form(f'peak_note_{case_id}'):
                observation = st.selectbox('Observation type',POSITIONS,key=f'peak_position_{case_id}')
                note = st.text_area('Peak observation',key=f'peak_note_text_{case_id}')
                save = st.form_submit_button('Save peak annotation',type='primary')
            if save:
                try:
                    store.annotate(case_id,run_id,mz,observation,note)
                    st.success('Peak observation saved.')
                    bundle = store.bundle(case_id)
                except ValueError as exc:
                    st.error(str(exc))
            if bundle['annotations']:
                st.dataframe(pd.DataFrame(bundle['annotations'])[['mz','position','note','run_id','created']],hide_index=True,width='stretch')
    with review:
        with st.form(f'case_review_{case_id}'):
            analyst = st.text_input('Analyst or reviewer name',case['analyst'],key=f'review_analyst_{case_id}')
            status = st.selectbox('Review status',STATUSES,index=STATUSES.index(case['status']),key=f'review_status_{case_id}')
            interpretation = st.text_area('Working interpretation',case['interpretation'],height=140,key=f'review_interpretation_{case_id}')
            conflicts = st.text_area('Conflicting evidence and open questions',case['conflicts'],height=140,key=f'review_conflicts_{case_id}')
            save = st.form_submit_button('Save review notes',type='primary')
        if save:
            store.update(case_id,analyst,status,interpretation,conflicts)
            st.success('Review notes saved.')
        st.caption('Review status is entered by the analyst; it is not an independent approval or a confirmation of chemical identity.')
    with export:
        bundle = store.bundle(case_id)
        export_key = f'notebook_export_{case_id}'
        signature = hashlib.sha256(json.dumps(bundle,sort_keys=True).encode()).hexdigest()
        if st.button('Prepare case export',type='primary',key=f'case_prepare_{case_id}'):
            try:
                with st.spinner('Checking attachments and preparing the case package…'):
                    st.session_state[export_key] = {'signature':signature,'files':store.export(case_id)}
            except ValueError as exc:
                st.error(f'Export blocked by an evidence integrity check: {exc}')
        prepared = st.session_state.get(export_key)
        if prepared and prepared['signature'] == signature:
            archive, html, content = prepared['files']
            a,b,c = st.columns(3)
            a.download_button('Case package · ZIP',archive,f'case-{case_id[:12]}.zip','application/zip',key=f'case_zip_{case_id}')
            b.download_button('Printable report · HTML',html,f'case-{case_id[:12]}.html','text/html',key=f'case_html_{case_id}')
            c.download_button('Case data · JSON',content,f'case-{case_id[:12]}.json','application/json',key=f'case_json_{case_id}')
        elif prepared:
            st.info('This notebook has changed. Prepare a new export to include the latest evidence and notes.')
        st.caption('ZIP includes a printable report, complete analysis snapshots, annotations, notes, activity records, and original evidence files. Open report.html in a browser to print or save as PDF.')
        if bundle['activity']:
            st.dataframe(pd.DataFrame(bundle['activity']),hide_index=True,width='stretch')
        st.info(bundle['limitations'])
    for box,label,key in zip(count_boxes,['Linked analyses','Evidence files','Peak annotations'],['analyses','attachments','annotations']):
        box.metric(label,len(bundle[key]))
