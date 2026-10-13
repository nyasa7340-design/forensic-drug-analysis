/** Small semantic rendering helpers. Untrusted names and notes are always escaped. */
export const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
export const number = (value, decimals=3) => value == null ? 'Not available' : Number(value).toLocaleString(undefined,{maximumFractionDigits:decimals,minimumFractionDigits:decimals});

export function table(rows, columns, action) {
  if (!rows.length) return '<p class="empty">No records to display.</p>';
  return `<table><thead><tr>${columns.map(c=>`<th scope="col">${escape(c.label || c.key)}</th>`).join('')}${action?'<th scope="col">Action</th>':''}</tr></thead><tbody>${rows.map(row=>`<tr>${columns.map(c=>`<td>${escape(c.format?c.format(row[c.key],row):row[c.key])}</td>`).join('')}${action?`<td>${action(row)}</td>`:''}</tr>`).join('')}</tbody></table>`;
}

export function metrics(items) {
  return `<div class="stat-grid">${items.map(([label,value])=>`<article class="stat"><span>${escape(label)}</span><strong>${escape(value)}</strong></article>`).join('')}</div>`;
}

export function spectrum(vector, title, style='chart-input', mirror) {
  const values=vector.map(Number), max=Math.max(100,...values.map(Math.abs));
  const signed=values.some(value=>value<0), width=950, left=52, right=920, base=(mirror||signed)?120:180, top=20;
  const yscale=(signed?100:base-top)/max;
  const x=mass=>left+(mass-10)/540*(right-left);
  const stems=values.map((v,i)=>Math.abs(v)>1e-9?`<line x1="${x(i+10).toFixed(2)}" x2="${x(i+10).toFixed(2)}" y1="${base}" y2="${(base-v*yscale).toFixed(2)}"/>`:'').join('');
  const mirrored=mirror?mirror.map((v,i)=>v>0?`<line x1="${x(i+10).toFixed(2)}" x2="${x(i+10).toFixed(2)}" y1="${base}" y2="${(base+v*.95).toFixed(2)}"/>`:'').join(''):'';
  const height=(mirror||signed)?265:240;
  return `<article class="chart-card"><h3>${escape(title)}</h3><svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escape(title)}. Mass channels 10 to 550; relative intensities."><line class="chart-axis" x1="${left}" y1="${base}" x2="${right}" y2="${base}"/><g class="${style}">${stems}</g><g class="chart-fit">${mirrored}</g>${[10,100,200,300,400,550].map(m=>`<text class="chart-label" x="${x(m)}" y="${height-27}" text-anchor="middle">${m}</text>`).join('')}<text class="chart-label" x="475" y="${height-8}" text-anchor="middle">m/z · nominal mass</text><text class="chart-label" x="10" y="16">Intensity</text></svg></article>`;
}

export function sweepChart(rows) {
  const point=(x,y)=>`${(55+x*8.3).toFixed(2)},${(210-y*1.8).toFixed(2)}`;
  return `<article class="chart-card"><h3>Reference A · input vs recovered coefficient</h3><svg viewBox="0 0 950 265" role="img" aria-label="Input versus recovered reference A coefficient across eleven mixing ratios"><line class="chart-axis" x1="55" y1="210" x2="885" y2="210"/><polyline class="chart-ideal" points="${point(0,0)} ${point(100,100)}"/><polyline class="chart-line" points="${rows.map(r=>point(r.input_A_percent,r.recovered_A_percent)).join(' ')}"/>${[0,20,40,60,80,100].map(n=>`<text class="chart-label" x="${55+n*8.3}" y="232" text-anchor="middle">${n}%</text><text class="chart-label" x="42" y="${214-n*1.8}" text-anchor="end">${n}%</text>`).join('')}<text class="chart-label" x="460" y="255" text-anchor="middle">Input A coefficient</text></svg><p class="help">Solid: recovered coefficient. Dashed: ideal recovery.</p></article>`;
}

export function reportHtml(report) {
  const exact=report.exact_match_entry_ids || [];
  const isMixture=Array.isArray(report.simulation)&&report.simulation.length>1;
  const isReferenceHoldout=Boolean(report.reference_holdout);
  const mixtureQuality=report.relative_residual>.2?'Mixture fit needs review':(report.relative_residual<.05?'Multi-component spectral fit':'Mixture screening fit');
  const headline=isMixture?mixtureQuality:report.best_name;
  const statusLabel=isMixture?'Mixture result':report.status;
  const warning=isReferenceHoldout
    ?'The selected reference and spectrally identical entries were withheld before scoring. These values measure how well the remaining library explains this known spectrum; they are not unknown-sample validation.'
    :isMixture
      ?(report.relative_residual>.2?'The mixture fit leaves substantial signal unexplained. Treat its fitted components as uncertain and review the input and residual.':'A single-reference ranking can be misleading for a mixture. Review all fitted components and the residual; simulator inputs are disclosed only for recovery scoring.')
      :(report.cosine_similarity<.85?'The best single-reference match is weak. Treat the result as inconclusive.':(report.peak_count<5?'Fewer than five populated mass bins provide limited evidence.':'A fitted combination does not establish chemical identity or sample purity.'));
  const resultContext=isReferenceHoldout
    ?`Withheld known entry #${escape(report.reference_holdout.selected_entry_id)} · ${escape(report.reference_holdout.selected_name)} · ${escape(report.reference_holdout.excluded_entry_ids.length)} identical reference(s) removed · ${escape(report.library_version)}`
    :isMixture
      ?`Closest single-reference screening hit: ${escape(report.best_name)} · entry #${escape(report.best_entry_id)}. This score does not summarize the whole mixture.`
      :`Local entry #${escape(report.best_entry_id)} · ${escape(report.library_version)}`;
  const resultMetrics=[
    [isReferenceHoldout?'Holdout cosine':'Cosine similarity',number(report.cosine_similarity,4)],
    [isReferenceHoldout?'Holdout-fit R²':'Fit R²',number(report.r_squared,4)],
    [isReferenceHoldout?'Holdout-fit RMSE':'RMSE',number(report.rmse)],
    [isReferenceHoldout?'Holdout residual / input':'Residual / input',number(report.relative_residual*100,2)+'%']
  ];
  return `<div class="split-heading"><h3>Analysis results</h3><span class="badge">Saved locally</span></div><p class="help">${escape(report.sample)} · ${escape(report.source)} · ${escape(report.timestamp)}</p>${metrics(resultMetrics)}<div class="result-heading"><span class="badge">${escape(statusLabel)}</span><h3>${escape(headline)}</h3><p class="help">${resultContext}</p></div><aside class="notice">${escape(warning)}${exact.length>1?` Exact matches share this spectral shape: ${escape(exact.join(', '))}.`:''}${report.excluded_peak_count?` ${escape(report.excluded_peak_count)} peaks outside m/z 10–550 were excluded.`:''}</aside>${spectrum(report.query,'Input spectrum')}${spectrum(report.reconstructed,'Reconstructed candidate fit','chart-fit')}${spectrum(report.residual,'Residual · input minus fit','chart-residual')}<details class="card" ${isMixture?'':'open'}><summary>${isMixture?'Ranked single-reference matches · screening only':'Ranked library matches'}</summary><div class="table-wrap">${table(report.matches,[{key:'entry_id',label:'Entry'},{key:'name',label:'Compound'},{key:'formula',label:'Formula'},{key:'mw',label:'Mass (Da)'},{key:'cosine_similarity',label:'Cosine similarity',format:v=>number(v,5)}])}</div></details><details class="card" ${isMixture?'open':''}><summary>Candidate fit weights${isMixture?' · review these components':''}</summary><p class="help">Relative coefficients of base-peak-normalized spectra, not concentration or purity. ${escape(report.candidate_count)} candidates fitted; similar spectra may have nonunique solutions.</p><div class="table-wrap">${table(report.components,[{key:'entry_id',label:'Entry'},{key:'name',label:'Compound'},{key:'fit_weight_percent',label:'Relative weight (%)',format:v=>number(v,4)},{key:'coefficient',label:'NNLS coefficient',format:v=>number(v,6)},{key:'indistinguishable_entry_ids',label:'Indistinguishable entries',format:v=>v.join(', ')}])}</div></details><div class="button-row"><a class="button secondary" href="/api/history/${encodeURIComponent(report.run_id)}/export?format=json" download>Download full report · JSON</a><a class="button secondary" href="/api/history/${encodeURIComponent(report.run_id)}/export?format=csv" download>Download spectra · CSV</a></div><p class="checksum">Library SHA-256: ${escape(report.library_sha256)}</p>`;
}
