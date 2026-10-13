import test from 'node:test';
import assert from 'node:assert/strict';
import {escape,spectrum,table,reportHtml} from './components.js';
import {csv} from './api.js';

test('Analyst-entered text remains text in tables',()=>{
  const html=table([{note:'<script>alert(1)</script>'}],[{key:'note'}]);
  assert.ok(!html.includes('<script>'));
  assert.ok(html.includes('&lt;script&gt;'));
  assert.equal(escape('"sample"'),'&quot;sample&quot;');
});
test('Signed residual peaks stay inside the SVG view box',()=>{
  const vector=Array(541).fill(0);vector[72]=-100;vector[184]=100;
  const chart=spectrum(vector,'Residual','chart-residual');
  const y=[...chart.matchAll(/y2="([\d.]+)"/g)].map(match=>Number(match[1]));
  assert.ok(y.includes(220));assert.ok(y.includes(20));
  assert.ok(y.every(value=>value>=0&&value<=265));
});
test('Mixture reports headline the component fit, not a misleading single reference',()=>{
  const report={simulation:[{name:'Flephedrone'},{name:'3-Ethylethcathinone'}],sample:'Synthetic mixture',source:'Simulator',timestamp:'today',cosine_similarity:.62,r_squared:1,rmse:0,relative_residual:0,peak_count:14,best_name:'Tamoxifen',best_entry_id:9,library_version:'test',query:Array(541).fill(0),reconstructed:Array(541).fill(0),residual:Array(541).fill(0),matches:[],components:[{entry_id:1,name:'Flephedrone',fit_weight_percent:50,coefficient:1,indistinguishable_entry_ids:[1]},{entry_id:2,name:'3-Ethylethcathinone',fit_weight_percent:50,coefficient:1,indistinguishable_entry_ids:[2]}],candidate_count:60,run_id:'fixture',library_sha256:'test'};
  const html=reportHtml(report);
  assert.ok(html.includes('Multi-component spectral fit'));
  assert.ok(html.includes('Closest single-reference screening hit: Tamoxifen'));
  assert.ok(html.includes('Candidate fit weights · review these components'));
  assert.ok(html.includes('Flephedrone'));
});
test('Reference self-check reports explain why its metrics are perfect',()=>{
  const report={source:'Reference self-check',sample:'Sildenafil',timestamp:'today',status:'Exact spectral match',cosine_similarity:1,r_squared:1,rmse:0,relative_residual:0,peak_count:8,best_name:'Sildenafil',best_entry_id:42,library_version:'test',query:Array(541).fill(0),reconstructed:Array(541).fill(0),residual:Array(541).fill(0),matches:[],components:[],candidate_count:0,run_id:'fixture',library_sha256:'test'};
  const html=reportHtml(report);
  assert.ok(html.includes('Self-match cosine'));
  assert.ok(html.includes('Workflow check only'));
  assert.ok(html.includes('compares a library spectrum with itself'));
  assert.ok(html.includes('Use Paste peaks or Upload file'));
});
test('CSV export preserves numeric signs and neutralizes text formulas',()=>{
  const output=csv([{name:'=1+1',residual:-4}],['name','residual']);
  assert.ok(output.includes('"\'=1+1"'));
  assert.ok(output.includes('"-4"'));
});
