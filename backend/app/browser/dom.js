(catalog = []) => {
  const visible = el => !!(el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
  const labelled = el => (el.getAttribute('aria-labelledby') || '').split(' ').map(id => document.getElementById(id)?.innerText || '').join(' ').trim();
  const label = el => ((el.labels ? [...el.labels].map(l => l.innerText).join(' ') : '') || labelled(el) || el.getAttribute('aria-label') || el.placeholder || el.name || '').trim();
  const consent = text => /\b(consent|agree|agreement|terms|privacy|certify|attest|acknowledge|subscribe|permission|affirm|declare|accept)\b/i.test(text);
  const unique = values => values.every(v => v && v.length <= 200) && new Set(values.map(v => v.toLowerCase())).size === values.length;
  const inspected = new Map();
  for (const item of catalog || []) {
    const matches = [...document.querySelectorAll('[data-aa-field]')].filter(e => e.getAttribute('data-aa-field') === item.key);
    if (matches.length === 1) inspected.set(matches[0], item);
  }
  document.querySelectorAll('[data-aa-field],[data-aa-options],[data-aa-step]').forEach(el => {
    el.removeAttribute('data-aa-field'); el.removeAttribute('data-aa-options'); el.removeAttribute('data-aa-step');
  });
  const controls = [...document.querySelectorAll('input,textarea,select,[role="combobox"],[role="radio"],[role="checkbox"],[role="textbox"],[contenteditable="true"]')].filter(visible);
  if (controls.length > 100) throw new Error('form_too_large');
  const seen = new Set(), consumed = new Set(), fields = [];
  for (const control of controls) {
    if (consumed.has(control)) continue;
    let el = control;
    let kind = el.tagName === 'SELECT' ? 'select' : el.tagName === 'TEXTAREA' ? 'textarea' : el.getAttribute('role') || el.type || 'text';
    if (el.isContentEditable) kind = 'rich_text';
    if (['hidden','submit','reset','button','image'].includes(kind)) continue;
    let question = label(el).slice(0,2000), options = [], manual = null, choices_on_open = false;
    let required = el.required || el.getAttribute('aria-required') === 'true';
    if (kind === 'radio') {
      const native = el.matches('input[type="radio"]');
      const root = native ? el.closest('fieldset,[role="radiogroup"]') : el.closest('[role="radiogroup"]');
      const members = root ? [...root.querySelectorAll('input[type="radio"],[role="radio"]')] : [];
      const peers = native ? [...document.querySelectorAll('input[type="radio"]')].filter(r => r.name === el.name && r.form === el.form) : members;
      const title = root ? (labelled(root) || root.getAttribute('aria-label') || root.querySelector(':scope > legend')?.innerText || '').trim() : '';
      if (root && title && members.length >= 2 && members.length <= 50 && members.every(r => visible(r) && !r.disabled && r.getAttribute('aria-disabled') !== 'true') &&
          (!native || (el.name && members.length === peers.length && members.every(r => r.matches('input[type="radio"]') && r.name === el.name && r.form === el.form))) &&
          (native || members.every(r => ['true','false'].includes(r.getAttribute('aria-checked'))))) {
        el = root; kind = 'radio_group'; question = title.slice(0,2000);
        options = members.map(r => label(r) || (r.getAttribute('role') === 'radio' ? r.innerText.trim() : '')); required = members.some(r => r.required) || root.getAttribute('aria-required') === 'true';
        members.forEach(r => consumed.add(r));
        if (!unique(options)) manual = 'Ambiguous or unlabelled radio choices';
        if (consent(question)) manual = 'Consent or attestation requires direct owner action';
      } else manual = 'Unlabelled, incomplete or ambiguous radio group: complete manually';
    } else if (kind === 'select') {
      options = [...el.options].filter(o => !o.disabled && o.value !== '').map(o => o.label.trim());
      if (el.multiple || options.length > 50 || !unique(options)) manual = 'Ambiguous or oversized choice list';
      else if (!options.length) manual = 'No choices available';
    } else if (kind === 'combobox') {
      const id = el.getAttribute('aria-controls');
      const lists = [...document.querySelectorAll('[role="listbox"]')].filter(l => l.id === id);
      const users = [...document.querySelectorAll('[role="combobox"]')].filter(c => c.getAttribute('aria-controls') === id);
      const list = lists.length === 1 ? lists[0] : null;
      const choices = list ? [...list.querySelectorAll('[role="option"]')] : [];
      options = choices.map(o => (o.getAttribute('aria-label') || o.textContent || '').trim());
      if (!id || !list || users.length !== 1 || !choices.length || choices.length > 50 || !unique(options) ||
          list.getAttribute('aria-multiselectable') === 'true' || choices.some(o => o.getAttribute('aria-disabled') === 'true') ||
          !(el.matches('input:not([type]),input[type="text"],input[type="search"],button[type="button"]')) ||
          !['true','false'].includes(el.getAttribute('aria-expanded'))) manual = 'Unsupported or ambiguous custom dropdown: complete manually';
      const known = inspected.get(el);
      if (!choices.length && known) {
        choices_on_open = true; options = known.options;
        manual = known.error || (!unique(options) || !options.length ? 'Unsupported dropdown choices' : null);
      }
    }
    const key = crypto.randomUUID();
    el.setAttribute('data-aa-field', key);
    if (kind === 'combobox' && !manual && !choices_on_open) {
      [...document.querySelectorAll('[role="listbox"]')].find(l => l.id === el.getAttribute('aria-controls')).setAttribute('data-aa-options', key);
    }
    if (!question) manual = 'Unlabelled field';
    else if (el.disabled || (el.readOnly && kind !== 'combobox') || el.getAttribute('aria-disabled') === 'true') manual = 'Read-only control';
    else if (!['text','email','tel','url','number','date','textarea','select','file','radio_group','combobox'].includes(kind)) manual ||= 'Consent, custom control or unsupported type: complete manually';
    else if (kind === 'file' && (!/resume|curriculum|cv\b/i.test(question) || el.multiple || (el.accept && !/\.pdf|application\/pdf/i.test(el.accept)))) manual = 'Only a single approved resume PDF is supported';
    if (['select','radio_group','combobox'].includes(kind) && consent([question, ...options].join(' '))) manual = 'Consent or attestation requires direct owner action';
    if (!['radio_group'].includes(kind) && controls.filter(other => other !== el && other.name && other.name === el.name).length) manual = 'Repeated control name: confirm manually';
    if (seen.has(question)) manual = 'Repeated label: confirm manually';
    seen.add(question);
    fields.push({key, accept: (el.accept || '').slice(0,200), question: question || 'Unlabelled field', kind, required, options: unique(options) && options.length <= 50 ? options : [], choices_on_open, max_characters: el.maxLength > 0 ? Math.min(el.maxLength,10000) : 1500, supported: !manual, manual_reason: manual});
  }
  const next = [...document.querySelectorAll('button[type="button"]')].filter(el => visible(el) && !el.disabled && el.getAttribute('aria-disabled') !== 'true' && !['radio','checkbox','combobox','option'].includes(el.getAttribute('role')) && !el.closest('[role="listbox"],[role="radiogroup"],[role="menu"]') && /^(next(?: step)?|continue)$/i.test((el.getAttribute('aria-label') || el.innerText).trim()));
  const steps = next.map(el => {
    const key = crypto.randomUUID(); el.setAttribute('data-aa-step', key);
    return {key, label: (el.getAttribute('aria-label') || el.innerText).trim(), supported: next.length === 1};
  });
  const step_heading = (document.querySelector('[aria-current="step"]')?.innerText || [...document.querySelectorAll('h2')].find(visible)?.innerText || '').trim().slice(0,200);
  return {
    fields,
    steps, step_heading,
    title: document.title.slice(0,200),
    heading: (document.querySelector('h1')?.innerText || '').slice(0,200),
    has_frames: !!document.querySelector('iframe'),
    blocked: !!document.querySelector('input[type="password"],iframe[src*="captcha"],[class*="captcha"],[id*="captcha"]') || /verify you are human|access denied|verification code|one.time password/i.test(document.body.innerText.slice(0,30000)),
    signature: JSON.stringify({fields: fields.map(({key,...f}) => f), steps: steps.map(({key,...s}) => s), step_heading}),
  };
}
