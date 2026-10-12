import {api,filePayload} from './api.js';
import {escape,table,number,metrics} from './components.js';

/** Notebook UI uses snapshots retrieved from the server; it never forges reports. */
export function notebookController(notify,busy,getHistory) {
  const select=document.querySelector('#notebook-select'), body=document.querySelector('#notebook-body');
  let current=null;
  async function refresh(selected) {
    const cases=await api('notebooks');
    select.innerHTML=cases.length?cases.map(c=>`<option value="${escape(c.id)}">${escape(c.title)} · ${escape(c.status)}</option>`).join(''):'<option value="">No notebooks saved yet</option>';
    if (selected && cases.some(c=>c.id===selected)) select.value=selected;
    document.querySelector('#create-notebook').open=!cases.length;
    if (cases.length) await open(select.value); else body.innerHTML='<p class="empty">Create a notebook to link analyses, attach evidence, and record observations.</p>';
  }
  async function open(id) {
    if (!id) return;
    current=await api(`notebooks/${id}`);
    const {case:c,analyses,attachments,annotations,activity}=current;
    const history=await getHistory();
    const runOptions=history.map(r=>`<option value="${escape(r.id)}">${escape(r.timestamp)} · ${escape(r.sample)}</option>`).join('');
    const linked=analyses.map(r=>r.report);
    body.innerHTML=`<p class="help">Case ${escape(c.id.slice(0,12))} · Sample: ${escape(c.sample || 'Not recorded')} · Created ${escape(c.created)}</p>${metrics([['Linked analyses',analyses.length],['Evidence files',attachments.length],['Peak annotations',annotations.length],['Review status',c.status]])}<div class="notebook-grid"><article class="card"><h3>Linked analyses</h3><form id="case-link-form"><label for="case-run">Saved analysis</label><select id="case-run" ${history.length?'':'disabled'}>${runOptions || '<option>No saved analyses yet</option>'}</select><button ${history.length?'':'disabled'}>Link analysis snapshot</button></form><p class="help">Snapshots preserve the original vectors, results, library checksum, and simulation settings.</p><div class="table-wrap">${table(linked,[{key:'sample',label:'Sample'},{key:'best_name',label:'Best match'},{key:'cosine_similarity',label:'Cosine',format:v=>number(v,4)}])}</div></article><article class="card"><h3>Supporting evidence</h3><form id="case-attachment-form"><label for="evidence-kind">Evidence type</label><select id="evidence-kind">${['Chromatogram','FTIR evidence','Instrument report','Reference documentation','Other supporting evidence'].map(k=>`<option>${k}</option>`).join('')}</select><label for="evidence-file">File · up to 20 MB</label><input id="evidence-file" type="file" accept=".pdf,.png,.jpg,.jpeg,.csv,.txt,.jdx,.dx" required><label for="evidence-note">Description or observation</label><textarea id="evidence-note" rows="3"></textarea><button>Save evidence</button></form><p class="help">Attachments support manual review. They do not alter calculated spectral results.</p>${attachments.map(a=>`<details><summary>${escape(a.kind)} · ${escape(a.name)}</summary><p>${escape(a.notes || 'No description recorded.')}</p><p class="checksum">SHA-256 ${escape(a.sha256)}</p><a href="/api/notebooks/${c.id}/attachments/${a.id}" download>Download original evidence</a></details>`).join('')}</article><article class="card"><h3>Peak annotations</h3>${linked.length?`<form id="case-peak-form"><label for="annotation-run">Linked analysis</label><select id="annotation-run">${linked.map(r=>`<option value="${escape(r.run_id)}">${escape(r.sample)}</option>`).join('')}</select><label for="annotation-mz">Peak m/z</label><input id="annotation-mz" type="number" min="10" max="550" step="1" value="82" required><p id="annotation-values" class="help"></p><label for="annotation-position">Observation type</label><select id="annotation-position">${['Supports interpretation','Conflicts with interpretation','Unresolved observation'].map(p=>`<option>${p}</option>`).join('')}</select><label for="annotation-note">Peak observation</label><textarea id="annotation-note" required></textarea><button>Save peak annotation</button></form>`:'<p class="help">Link an analysis before annotating its peaks.</p>'}<div class="table-wrap">${table(annotations,[{key:'mz',label:'m/z'},{key:'position',label:'Observation'},{key:'note',label:'Note'}])}</div></article><article class="card"><h3>Review notes</h3><form id="case-review-form"><label for="review-analyst">Analyst or reviewer name</label><input id="review-analyst" value="${escape(c.analyst)}" maxlength="150"><label for="review-status">Review status</label><select id="review-status">${['Draft','Awaiting review','Reviewed'].map(s=>`<option ${s===c.status?'selected':''}>${s}</option>`).join('')}</select><label for="review-interpretation">Working interpretation</label><textarea id="review-interpretation">${escape(c.interpretation)}</textarea><label for="review-conflicts">Conflicting evidence and open questions</label><textarea id="review-conflicts">${escape(c.conflicts)}</textarea><button>Save review notes</button></form><p class="help">Status is analyst-entered; it is not independent approval or confirmation of identity.</p></article><article class="card full-width"><h3>Report & activity</h3><div class="button-row"><a class="button secondary" href="/api/notebooks/${c.id}/export?format=zip" download>Case package · ZIP</a><a class="button secondary" href="/api/notebooks/${c.id}/export?format=html" download>Printable report · HTML</a><a class="button secondary" href="/api/notebooks/${c.id}/export?format=json" download>Case data · JSON</a></div><p class="help">ZIP includes the report, full analysis snapshots, original evidence files, notes, and activity records.</p><div class="table-wrap">${table(activity,[{key:'created',label:'Time'},{key:'action',label:'Action'},{key:'details',label:'Details'}])}</div><aside class="notice">${escape(current.limitations)}</aside></article></div>`;
    async function submit(form, action, payload) {
      form.addEventListener('submit', async event=>{
        event.preventDefault();
        await busy(form,async()=>{
          await api(`notebooks/${c.id}/${action}`,await payload());
          await refresh(c.id); notify('Notebook saved.');
        });
      });
    }
    submit(document.querySelector('#case-link-form'),'link',()=>({run_id:document.querySelector('#case-run').value}));
    submit(document.querySelector('#case-attachment-form'),'attach',async()=>({file:await filePayload(document.querySelector('#evidence-file').files[0]),kind:document.querySelector('#evidence-kind').value,notes:document.querySelector('#evidence-note').value}));
    submit(document.querySelector('#case-review-form'),'update',()=>({analyst:document.querySelector('#review-analyst').value,status:document.querySelector('#review-status').value,interpretation:document.querySelector('#review-interpretation').value,conflicts:document.querySelector('#review-conflicts').value}));
    if (linked.length) {
      const values=()=>{
        const report=linked.find(r=>r.run_id===document.querySelector('#annotation-run').value);
        const index=Number(document.querySelector('#annotation-mz').value)-10;
        document.querySelector('#annotation-values').textContent=Number.isInteger(index)&&index>=0&&index<541?`Input ${number(report.query[index])} · Fit ${number(report.reconstructed[index])} · Residual ${number(report.residual[index])}`:'Choose a nominal m/z from 10 to 550.';
      };
      document.querySelector('#annotation-run').addEventListener('change',values);
      document.querySelector('#annotation-mz').addEventListener('input',values); values();
      submit(document.querySelector('#case-peak-form'),'annotate',()=>({run_id:document.querySelector('#annotation-run').value,mz:Number(document.querySelector('#annotation-mz').value),position:document.querySelector('#annotation-position').value,note:document.querySelector('#annotation-note').value}));
    }
  }
  select.addEventListener('change',()=>busy(select,()=>open(select.value)));
  const create=document.querySelector('#notebook-create-form');
  create.addEventListener('submit',async event=>{
    event.preventDefault();
    await busy(create,async()=>{
      const c=await api('notebooks',{title:document.querySelector('#case-title').value,sample:document.querySelector('#case-sample').value,analyst:document.querySelector('#case-analyst').value});
      create.reset(); await refresh(c.id); notify('Evidence notebook created.');
    });
  });
  return {refresh};
}
