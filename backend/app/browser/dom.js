() => {
  const visible = el => !!(el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
  const controls = [...document.querySelectorAll('input,textarea,select,[role="combobox"],[role="radio"],[role="checkbox"]')].filter(visible);
  if (controls.length > 100) throw new Error('form_too_large');
  const seen = new Set();
  const fields = [];
  for (const el of controls) {
    const kind = el.tagName === 'SELECT' ? 'select' : el.tagName === 'TEXTAREA' ? 'textarea' : el.getAttribute('role') || el.type || 'text';
    if (['hidden','submit','reset','button','image'].includes(kind)) continue;
    const labels = el.labels ? [...el.labels].map(l => l.innerText).join(' ') : '';
    const labelled = (el.getAttribute('aria-labelledby') || '').split(' ').map(id => document.getElementById(id)?.innerText || '').join(' ');
    const question = (labels || labelled || el.getAttribute('aria-label') || el.placeholder || el.name || '').trim().slice(0,2000);
    const options = kind === 'select' ? [...el.options].filter(o => !o.disabled && o.value !== '').map(o => o.label.trim()).slice(0,51) : [];
    const key = crypto.randomUUID();
    el.setAttribute('data-aa-field', key);
    let manual = null;
    if (!question) manual = 'Unlabelled field';
    else if (el.disabled || el.readOnly) manual = 'Read-only control';
    else if (!['text','email','tel','url','number','date','textarea','select','file'].includes(kind)) manual = 'Consent, custom control or unsupported type: complete manually';
    else if (kind === 'file' && (!/resume|curriculum|cv\b/i.test(question) || el.multiple || (el.accept && !/\.pdf|application\/pdf/i.test(el.accept)))) manual = 'Only a single approved resume PDF is supported';
    else if (kind === 'select' && (el.multiple || options.length > 50 || new Set(options).size !== options.length)) manual = 'Ambiguous or oversized choice list';
    else if (kind === 'select' && !options.length) manual = 'No choices available';
    if (controls.filter(other => other !== el && other.name && other.name === el.name).length) manual = 'Repeated control name: confirm manually';
    if (seen.has(question)) manual = 'Repeated label: confirm manually';
    seen.add(question);
    fields.push({key, accept: (el.accept || '').slice(0,200), question: question || 'Unlabelled field', kind, required: el.required || el.getAttribute('aria-required') === 'true', options: options.slice(0,50), max_characters: el.maxLength > 0 ? Math.min(el.maxLength,10000) : 1500, supported: !manual, manual_reason: manual});
  }
  return {
    fields,
    title: document.title.slice(0,200),
    heading: (document.querySelector('h1')?.innerText || '').slice(0,200),
    has_frames: !!document.querySelector('iframe'),
    blocked: !!document.querySelector('input[type="password"],iframe[src*="captcha"],[class*="captcha"],[id*="captcha"]') || /verify you are human|access denied|verification code|one.time password/i.test(document.body.innerText.slice(0,30000)),
    signature: JSON.stringify(fields.map(({key,...f}) => f)),
  };
}
