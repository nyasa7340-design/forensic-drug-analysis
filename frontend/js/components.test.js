import test from 'node:test';
import assert from 'node:assert/strict';
import {escape,spectrum,table} from './components.js';
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
test('CSV export preserves numeric signs and neutralizes text formulas',()=>{
  const output=csv([{name:'=1+1',residual:-4}],['name','residual']);
  assert.ok(output.includes('"\'=1+1"'));
  assert.ok(output.includes('"-4"'));
});
