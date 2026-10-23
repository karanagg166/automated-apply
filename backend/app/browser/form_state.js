async () => {
  const forms = [...document.forms].filter(f => f.getClientRects().length);
  if (forms.length !== 1) throw new Error('ambiguous_form');
  const form = forms[0];
  const entries = [];
  for (const [name, value] of new FormData(form).entries()) {
    if (['_aa_attempt_id','_aa_payload_digest'].includes(name)) continue;
    // Hash the bytes' text representation used by native multipart encoding.
    // Visible control values below retain their original textarea API newlines.
    if (typeof value === 'string') entries.push([name, value.replace(/\r\n|\r|\n/g, '\r\n')]);
    else {
      if (value.size > 5*1024*1024) throw new Error('oversized_upload');
      const hash = [...new Uint8Array(await crypto.subtle.digest('SHA-256', await value.arrayBuffer()))].map(n => n.toString(16).padStart(2,'0')).join('');
      entries.push([name, {name: value.name, sha256: hash, size: value.size}]);
    }
  }
  const controls = [...form.elements].filter(e => e.getClientRects().length && !['submit','button','hidden','reset'].includes(e.type));
  if (controls.length > 100) throw new Error('form_too_large');
  return {
    action: form.action, method: form.method.toUpperCase(), enctype: form.enctype,
    fixture: form.getAttribute('data-aa-mock-fixture'),
    valid: [...form.elements].every(e => !e.willValidate || e.validity.valid),
    entries,
    controls: controls.map(e => ({key: e.getAttribute('data-aa-field'), name: e.name, kind: e.type,
      value: e.type === 'file' ? null : e.tagName === 'SELECT' ? e.selectedOptions[0]?.label : e.value,
      checked: e.checked || false, required: e.required || e.getAttribute('aria-required') === 'true',
      disabled: e.disabled, file_count: e.files?.length || 0})),
  };
}
