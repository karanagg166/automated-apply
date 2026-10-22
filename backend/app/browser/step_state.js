async fields => {
  const visible = e => !!(e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');
  const forms = [...document.forms].filter(visible);
  if (forms.length !== 1 || forms[0].elements.length > 200) throw new Error('ambiguous_step_form');
  const form = forms[0], entries = [];
  let uploadBytes = 0;
  for (const [name, value] of new FormData(form)) {
    if (entries.length >= 200 || name.length > 200) throw new Error('oversized_step');
    if (typeof value === 'string') {
      if (value.length > 10000) throw new Error('oversized_value');
      entries.push([name, value]);
    } else {
      uploadBytes += value.size;
      if (value.size > 5*1024*1024 || uploadBytes > 10*1024*1024) throw new Error('oversized_upload');
      const sha256 = [...new Uint8Array(await crypto.subtle.digest('SHA-256', await value.arrayBuffer()))].map(n => n.toString(16).padStart(2,'0')).join('');
      entries.push([name, {name: value.name, size: value.size, sha256}]);
    }
  }
  const values = [];
  for (const field of fields) {
    const elements = document.querySelectorAll(`[data-aa-field="${field.key}"]`);
    if (elements.length !== 1) throw new Error('changed_step');
    const e = elements[0];
    let value = e.value ?? '', complete = !e.validity || e.validity.valid;
    if (field.kind === 'radio_group') {
      const selected = [...e.querySelectorAll('input[type="radio"],[role="radio"]')].filter(r => r.checked || r.getAttribute('aria-checked') === 'true');
      value = selected.map(r => (r.labels ? [...r.labels].map(l => l.innerText).join(' ') : '') || r.getAttribute('aria-label') || r.innerText || '').join(', ').trim();
      complete = selected.length <= 1 && (!field.required || selected.length === 1);
    } else if (field.kind === 'checkbox' || field.kind === 'radio') {
      value = e.checked ? 'Selected' : 'Unselected'; complete = !field.required || e.checked;
    } else if (field.kind === 'file') {
      value = [...e.files].map(f => f.name).join(', '); complete = !field.required || e.files.length > 0;
    } else if (field.kind === 'select') value = e.selectedOptions[0]?.label || '';
    else if (field.kind === 'combobox') value = e.tagName === 'INPUT' ? e.value : e.innerText.trim();
    if (String(value).length > 10000) throw new Error('oversized_value');
    if (field.required && !String(value).trim()) complete = false;
    if (field.options.length && !['checkbox','radio'].includes(field.kind) && value && !field.options.includes(value)) complete = false;
    if (field.required && !field.supported && !['checkbox','radio_group'].includes(field.kind)) complete = false;
    values.push({question: field.question, kind: field.kind, value: String(value), complete, required: field.required,
      consent: !field.supported && ['checkbox','radio_group'].includes(field.kind)});
  }
  return {entries, action: form.action, method: form.method, values, submission_blocks: window.__aaSubmissionBlocks || 0,
    complete: values.every(v => v.complete)};
}
