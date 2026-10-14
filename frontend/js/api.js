import {API_BASE_URL} from './config.js';

export function apiUrl(path) {
  return `${API_BASE_URL.replace(/\/+$/, '')}/api/${path}`;
}

/** Transport to the local server or the configured Render API. */
export async function api(path, data) {
  let response;
  try {
    response = await fetch(apiUrl(path), data === undefined ? {} : {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)
    });
  } catch { throw new Error(API_BASE_URL ? 'The analysis server is unavailable. Check the backend URL and allowed website origin.' : 'The analysis server is unavailable. Start it with python server.py.'); }
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'The request could not be completed.');
  return result;
}

export function filePayload(file) {
  if (!file) return Promise.reject(new Error('Select a file first.'));
  if (file.size > 20 * 1024 * 1024) return Promise.reject(new Error('Each file must be no larger than 20 MB.'));
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve({name:file.name, data:String(reader.result).split(',')[1]});
    reader.onerror = () => reject(new Error('The selected file could not be read.'));
    reader.readAsDataURL(file);
  });
}

export function download(data, filename, type='application/json') {
  const url = URL.createObjectURL(new Blob([data], {type}));
  const anchor = document.createElement('a');
  anchor.href=url; anchor.download=filename; anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function csv(rows, columns) {
  const cell = value => {
    let text = String(value ?? '');
    // Prevent analyst-entered text from becoming a spreadsheet formula on import.
    if (typeof value === 'string' && /^[=+@-]/.test(text)) text="'"+text;
    return '"'+text.replaceAll('"','""')+'"';
  };
  return [columns.map(cell).join(','), ...rows.map(row => columns.map(key => cell(row[key])).join(','))].join('\r\n');
}
