import {api,filePayload,download,csv} from './api.js';
import {escape,number,table,metrics,spectrum,sweepChart,reportHtml} from './components.js?v=analysis-csv-20261013';
import {notebookController} from './notebook.js';

const $=selector=>document.querySelector(selector);
const state={library:[],history:[],filtered:[],page:0,upload:null,analysisStale:false};
const titles={overview:'Workspace overview',analysis:'Spectrum analysis',simulator:'Mixture experiments',batch:'Batch analysis',library:'Reference library',history:'Analysis history',notebook:'Evidence notebook',methodology:'Methods & interpretation'};

function notify(message,error=false) {
  const box=$('#notification');box.textContent=message;box.hidden=false;
  box.classList.toggle('error',error);box.setAttribute('role',error?'alert':'status');
  if (error) $('#workspace').scrollTop=0;
}

async function busy(container,work) {
  const controls=container.matches('button,select')?[container]:[...container.querySelectorAll('button')];
  const previous=controls.map(c=>c.disabled);controls.forEach(c=>c.disabled=true);container.setAttribute('aria-busy','true');
  try {return await work();} catch(error) {notify(error.message,true);}
  finally {controls.forEach((c,i)=>c.disabled=previous[i]);container.removeAttribute('aria-busy');}
}

async function refreshHistory() {state.history=await api('history');return state.history;}
function invalidateAnalysisResults() {
  const output=$('#analysis-results');
  if(!output.innerHTML.trim()||state.analysisStale)return;
  state.analysisStale=true;
  output.innerHTML='<aside class="notice analysis-stale" role="status"><strong>Input changed.</strong> Previous metrics were cleared. Submit Analyze spectrum to calculate results for the current input.</aside>';
}
const notebooks=notebookController(notify,busy,refreshHistory);

async function refreshOverview() {
  const [status]=await Promise.all([api('status'),refreshHistory()]);
  $('#overview-stats').innerHTML=metrics([['Reference spectra',status.references.toLocaleString()],['Mass channels',status.channels],['Saved analyses',status.saved_analyses],['Evidence notebooks',status.notebooks]]).replace(/^<div class="stat-grid">|<\/div>$/g,'');
  $('#connection-label').textContent=`${status.references.toLocaleString()} reference spectra · Ready`;
  $('#connection-light').classList.add('connected');
  $('#library-checksum').textContent=`Bundled spectral data SHA-256: ${status.library_sha256}`;
  $('#recent-runs').innerHTML=table(state.history.slice(0,5),[{key:'sample',label:'Sample'},{key:'best_name',label:'Best reference match'},{key:'timestamp',label:'Saved at'}],row=>`<button class="secondary" data-open-run="${escape(row.id)}">Inspect</button>`);
}

function historyTable() {
  $('#history-table').innerHTML=table(state.history,[{key:'timestamp',label:'Saved at'},{key:'sample',label:'Sample'},{key:'source',label:'Input source'},{key:'best_name',label:'Best reference'}],row=>`<button class="secondary" data-open-run="${escape(row.id)}">Restore</button>`);
}

async function route(moveFocus=false) {
  const requested=location.hash.slice(1), name=Object.hasOwn(titles,requested)?requested:'overview';
  $('#notification').hidden=true;
  document.querySelectorAll('.page').forEach(page=>page.hidden=page.id!==`page-${name}`);
  document.querySelectorAll('[data-route]').forEach(link=>{
    if(link.dataset.route===name)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');
  });
  $('#page-label').textContent=titles[name];$('#workspace').scrollTop=0;
  document.title=`${titles[name]} · forensic-drug-analysis`;
  $('#main-navigation').classList.remove('open');$('#menu-toggle').setAttribute('aria-expanded','false');
  if(moveFocus){const heading=$(`#page-${name} h2`);heading.setAttribute('tabindex','-1');heading.focus({preventScroll:true});}
  if(!state.library.length)return;
  await busy($('#workspace'),async()=>{
    if(name==='overview')await refreshOverview();
    if(name==='history'){await refreshHistory();historyTable();}
    if(name==='notebook')await notebooks.refresh($('#notebook-select').value);
  });
}
window.addEventListener('hashchange',()=>route(true));
$('.skip-link').addEventListener('click',event=>{event.preventDefault();$('#workspace').focus();});
$('#menu-toggle').addEventListener('click',()=>{
  const open=$('#main-navigation').classList.toggle('open');$('#menu-toggle').setAttribute('aria-expanded',String(open));
});
document.addEventListener('keydown',event=>{if(event.key==='Escape'){$('#main-navigation').classList.remove('open');$('#menu-toggle').setAttribute('aria-expanded','false');}});

// Input parsing stays on the server, matching the existing validation behavior.
$('#analysis-form').addEventListener('change',event=>{
  if(event.target.name==='input-mode')for(const mode of ['reference','text','file'])$(`#analysis-${mode}`).hidden=event.target.value!==mode;
  invalidateAnalysisResults();
});
$('#analysis-form').addEventListener('input',event=>{
  if(event.target.matches('#sample-name,#peak-text'))invalidateAnalysisResults();
});
$('#spectrum-file').addEventListener('change',()=>busy($('#analysis-form'),async()=>{
  state.upload=null;$('#file-record').disabled=true;
  const file=await filePayload($('#spectrum-file').files[0]), records=await api('parse',file);
  state.upload=file;$('#file-record').innerHTML=records.map((r,i)=>`<option value="${i}">${escape(r.name)} · ${r.peak_count} bins${r.excluded_peak_count?` · ${r.excluded_peak_count} excluded`:''}</option>`).join('');$('#file-record').disabled=false;
  $('#file-help').textContent=`${records.length} spectrum record(s) parsed. Only the selected record is analyzed.`;
}));
$('#analysis-form').addEventListener('submit',event=>{
  event.preventDefault();busy(event.currentTarget,async()=>{
    const mode=$('input[name="input-mode"]:checked').value;
    const payload=mode==='reference'?{mode,entry_id:Number($('#analysis-entry').value)}:mode==='text'?{mode,name:$('#sample-name').value,text:$('#peak-text').value}:{mode,file:state.upload,record:Number($('#file-record').value)};
    if(mode==='file'&&!state.upload)throw new Error('Select and parse a spectrum file first.');
    const report=await api('analyze',payload);$('#analysis-results').innerHTML=reportHtml(report);state.analysisStale=false;notify('Analysis saved. Review the results below.');await refreshOverview();
  });
});

function simulatorPayload(mode) {
  const third=$('#third-enabled').checked, a=Number($('#share-a').value), c=third?Number($('#share-c').value):0;
  if(a+c>100)throw new Error('Reference A and C coefficients cannot exceed 100% together.');
  return {mode,entry_ids:[Number($('#sim-a').value),Number($('#sim-b').value),...(third?[Number($('#sim-c').value)]:[])],shares:[a,100-a-c,...(third?[c]:[])],noise:Number($('#sim-noise').value),loss:Number($('#sim-loss').value),extra:Number($('#sim-extra').value),seed:Number($('#sim-seed').value)};
}
function updateShares() {
  const third=$('#third-enabled').checked;$('#third-reference').hidden=!third;$('#share-c').disabled=!third;
  const b=100-Number($('#share-a').value)-(third?Number($('#share-c').value):0);$('#share-summary').textContent=`Reference B coefficient: ${b}%. These are normalized signal coefficients, not concentration.`;
}
['third-enabled','share-a','share-c'].forEach(id=>$(`#${id}`).addEventListener('input',updateShares));
$('#simulator-form').addEventListener('submit',event=>{
  event.preventDefault();const action=event.submitter?.value || 'preview';busy(event.currentTarget,async()=>{
    const payload=simulatorPayload(action), result=await api('simulate',payload);
    if(action==='sweep') {
      $('#simulation-output').innerHTML=`<aside class="notice"><strong>Controlled two-reference sweep</strong>This fit uses only references A and B; C is excluded. Eleven trials with one seed do not establish detection limits or validated performance.</aside><p class="help">A: ${escape(result.references[0])} · B: ${escape(result.references[1])} · seed ${result.settings.seed}</p>${sweepChart(result.rows)}<div class="table-wrap">${table(result.rows,[{key:'input_A_percent',label:'Input A (%)'},{key:'recovered_A_percent',label:'Recovered A (%)',format:v=>number(v,4)},{key:'recovered_B_percent',label:'Recovered B (%)',format:v=>number(v,4)},{key:'A_absolute_error_pp',label:'A error (pp)',format:v=>number(v,6)},{key:'fit_rmse',label:'RMSE',format:v=>number(v,6)}])}</div><button id="sweep-download" class="secondary">Download sweep & settings</button><p class="help">Errors near machine precision are numerical roundoff.</p>`;
      $('#sweep-download').onclick=()=>download(JSON.stringify(result,null,2),'ratio-sweep.json');$('#simulation-results').innerHTML='';
    } else {
      const {experiment,diagnostics,truth}=result;
      const fitted=result.report?new Map(result.report.components.map(c=>[c.entry_id,c.fit_weight_percent])):null;
      const comparisons=truth.map(t=>({...t,recovered:fitted?.get(t.entry_id)||0,error:Math.abs((fitted?.get(t.entry_id)||0)-t.input_coefficient_percent)}));
      $('#simulation-output').innerHTML=`<p class="help">Seed ${experiment.settings.seed} · noise SD ${experiment.settings.noise_std_base_peak_percent} · peak loss ${experiment.settings.peak_loss_percent}% · extra ions requested ${experiment.settings.extra_ions_requested}</p>${metrics([['Challenge RMSE',number(experiment.distortion_rmse,2)],['Removed peaks',experiment.dropped_mz.length],['Extra ions',experiment.added_mz.length],['Basis condition',diagnostics.condition_number==null?'Dependent':number(diagnostics.condition_number,2)]])}${spectrum(experiment.clean,'Clean mixture · selected reference signals')}${spectrum(experiment.observed,'Challenged measurement')}<details class="card" open><summary>Reference contributions & recovery</summary><div class="table-wrap">${table(comparisons,[{key:'entry_id',label:'Entry'},{key:'name',label:'Reference'},{key:'input_coefficient_percent',label:'Input weight (%)'},...(fitted?[{key:'recovered',label:'Recovered weight (%)',format:v=>number(v,4)},{key:'error',label:'Absolute error (pp)',format:v=>number(v,4)}]:[])])}</div>${fitted?'<p class="help">The blind search receives only the challenged vector. Known inputs are used afterward for scoring. Inspect indistinguishable alternatives in the fit table.</p>':''}${experiment.contributions.map((vector,i)=>spectrum(vector,`${truth[i].name} · contribution to clean signal`)).join('')}</details><details class="card"><summary>Fingerprint overlap & distinguishing ions</summary><div class="table-wrap">${table(truth.map((t,i)=>({name:t.name,...Object.fromEntries(truth.map((other,j)=>[String(j),diagnostics.similarities[i][j]]))})),[{key:'name',label:'Reference'},...truth.map((t,j)=>({key:String(j),label:t.name,format:v=>number(v,4)}))])}</div><div class="table-wrap">${table(diagnostics.contrast_ions,[{key:'reference',label:'Reference'},{key:'mz',label:'m/z'},{key:'reference_intensity',label:'Intensity',format:v=>number(v,2)},{key:'largest_other_intensity',label:'Largest other',format:v=>number(v,2)},{key:'contrast',label:'Contrast',format:v=>number(v,2)}])}</div><p class="help">Distinguishing ions are relative to the selected set, not unique across the full library. Higher condition numbers indicate greater sensitivity to measurement changes.</p></details><details class="card"><summary>Altered channels</summary><p>Removed m/z: ${escape(experiment.dropped_mz.join(', ')||'None')}</p><p>Added m/z: ${escape(experiment.added_mz.join(', ')||'None')}</p></details><button id="blueprint-download" class="secondary">Download experiment blueprint</button>`;
      $('#blueprint-download').onclick=()=>download(JSON.stringify({truth,experiment,diagnostics},null,2),'mixture-blueprint.json');
      $('#simulation-results').innerHTML=result.report?reportHtml(result.report):'';
      if(result.report){notify('Blind recovery saved in analysis history.');await refreshOverview();}
    }
  });
});

$('#batch-form').addEventListener('submit',event=>{
  event.preventDefault();busy(event.currentTarget,async()=>{
    const files=await Promise.all([...$('#batch-files').files].map(filePayload));
    if(JSON.stringify({files}).length>30*1024*1024)throw new Error('Combined upload is too large. Select a smaller batch.');
    const result=await api('batch',{files});
    $('#batch-output').innerHTML=`${result.errors.length?`<aside class="notice"><strong>Some files could not be analyzed</strong>${result.errors.map(e=>`${escape(e.file)}: ${escape(e.error)}`).join('<br>')}</aside>`:''}<div class="table-wrap">${table(result.reports,[{key:'sample',label:'Sample'},{key:'best_name',label:'Best match'},{key:'status',label:'Status'},{key:'cosine_similarity',label:'Cosine',format:v=>number(v,4)}],r=>`<button class="secondary" data-batch-result="${escape(r.run_id)}">Inspect</button>`)}</div>${result.reports.length?'<button id="batch-download" class="secondary">Download full batch reports</button>':''}`;
    $('#batch-results').innerHTML='';
    if(result.reports.length)$('#batch-download').onclick=()=>download(JSON.stringify(result,null,2),'batch-reports.json');
    $('#batch-output').onclick=event=>{const button=event.target.closest('[data-batch-result]');if(button)$('#batch-results').innerHTML=reportHtml(result.reports.find(r=>r.run_id===button.dataset.batchResult));};
    notify(`${result.reports.length} spectrum result(s) saved; ${result.errors.length} file error(s).`);await refreshOverview();
  });
});

function filterLibrary() {
  const search=$('#library-search').value.trim().toLowerCase(), low=Number($('#mass-min').value), high=$('#mass-max').value===''?Infinity:Number($('#mass-max').value);
  state.filtered=state.library.filter(r=>r.mw>=low&&r.mw<=high&&(!search||r.name.toLowerCase().includes(search)||r.formula.toLowerCase().includes(search)||String(r.id)===search));state.page=0;renderLibrary();
}
function renderLibrary() {
  const pages=Math.max(1,Math.ceil(state.filtered.length/30));state.page=Math.min(pages-1,Math.max(0,state.page));
  $('#library-count').textContent=`${state.filtered.length.toLocaleString()} of ${state.library.length.toLocaleString()} entries`;
  $('#library-table').innerHTML=table(state.filtered.slice(state.page*30,(state.page+1)*30),[{key:'id',label:'Entry'},{key:'name',label:'Compound'},{key:'formula',label:'Formula'},{key:'mw',label:'Mass (Da)'},{key:'base_peak_mz',label:'Base peak'},{key:'num_peaks',label:'Peak count'}],r=>`<button class="secondary" data-reference="${r.id}">Spectrum</button>`);
  $('#library-page').textContent=`Page ${state.page+1} of ${pages}`;$('#library-prev').disabled=state.page===0;$('#library-next').disabled=state.page===pages-1;
}
['library-search','mass-min','mass-max'].forEach(id=>$(`#${id}`).addEventListener('input',filterLibrary));
$('#library-prev').onclick=()=>{state.page--;renderLibrary();};$('#library-next').onclick=()=>{state.page++;renderLibrary();};
$('#library-export').onclick=()=>download(csv(state.filtered,['id','name','formula','mw','base_peak_mz','num_peaks']),'reference-library.csv','text/csv');
$('#library-table').addEventListener('click',event=>{const button=event.target.closest('[data-reference]');if(button)busy(button,async()=>{
  const result=await api(`spectrum/${button.dataset.reference}`);$('#library-spectrum').innerHTML=spectrum(result.vector,`${result.entry.name} · entry #${result.entry.id}`)+'<button id="reference-download" class="secondary">Download reference peaks</button>';
  $('#reference-download').onclick=()=>download(csv(result.vector.map((intensity,i)=>({mz:i+10,intensity})).filter(r=>r.intensity>0),['mz','intensity']),`reference-${result.entry.id}.csv`,'text/csv');
});});
document.addEventListener('click',event=>{const button=event.target.closest('[data-open-run]');if(button)busy(button,async()=>{
  const report=await api(`history/${encodeURIComponent(button.dataset.openRun)}`);location.hash='history';await refreshHistory();historyTable();$('#history-results').innerHTML=reportHtml(report);
});});
$('#history-export').onclick=()=>download(csv(state.history,['id','timestamp','sample','source','best_name']),'analysis-history.csv','text/csv');

// Bootstrapping uses only real API values. Empty records stay explicitly empty.
await route();
try {
  state.library=await api('library');
  const options=state.library.map(r=>`<option value="${r.id}">${escape(r.name)} · #${r.id} · ${escape(r.formula)}</option>`).join('');
  document.querySelectorAll('.reference-select').forEach(select=>select.innerHTML=options);
  $('#analysis-entry').value='1747';$('#sim-a').value='1747';$('#sim-b').value='1110';$('#sim-c').value='1836';
  updateShares();filterLibrary();await refreshOverview();await route();
} catch(error) {$('#connection-label').textContent='Analysis server unavailable';notify(error.message,true);}
