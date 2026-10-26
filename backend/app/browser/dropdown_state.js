async () => {
  // Read values without FormData: its event can itself run untrusted handlers.
  const controls = [...document.querySelectorAll('input,textarea,select,button,[role="combobox"],[role="checkbox"],[role="radio"],[role="textbox"],[contenteditable="true"]')];
  if (controls.length > 200) throw new Error('oversized_dropdown_state');
  const state = [];
  let uploadBytes = 0;
  for (const e of controls) {
    const files = [];
    for (const file of (e.files || [])) {
      uploadBytes += file.size;
      if (file.size > 5*1024*1024 || uploadBytes > 10*1024*1024 || files.length >= 10) throw new Error('oversized_dropdown_upload');
      const sha256 = [...new Uint8Array(await crypto.subtle.digest('SHA-256', await file.arrayBuffer()))].map(n => n.toString(16).padStart(2,'0')).join('');
      files.push([file.name, file.size, file.type, file.lastModified, sha256]);
    }
    state.push({
    tag: e.tagName, type: e.type || '', name: e.name || '', role: e.getAttribute('role'),
    value: e.value ?? '', checked: e.checked ?? null, aria: e.getAttribute('aria-checked'),
    text: e.isContentEditable || e.getAttribute('role') === 'textbox' || (e.tagName === 'BUTTON' && e.getAttribute('role') === 'combobox') ? e.innerText : null,
    selected: e.tagName === 'SELECT' ? [...e.options].map(o => [o.value, o.selected]) : null,
    files,
    disabled: !!e.disabled, required: !!e.required, readonly: !!e.readOnly,
    });
  }
  const raw = JSON.stringify({state, url: location.href, title: document.title,
    heading: document.querySelector('h1')?.innerText || '', blocks: window.__aaSubmissionBlocks || 0});
  if (raw.length > 131072) throw new Error('oversized_dropdown_state');
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(raw)))].map(n => n.toString(16).padStart(2,'0')).join('');
}
