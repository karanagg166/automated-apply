({key, eligibility = false}) => {
  if (!/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/.test(key)) throw new Error('invalid_dropdown_handle');
  const controls = document.querySelectorAll(`[data-aa-field="${key}"]`);
  if (controls.length !== 1) return null;
  const e = controls[0], visible = el => !!(el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
  if (!visible(e) || e.disabled || e.getAttribute('aria-disabled') === 'true' || e.getAttribute('role') !== 'combobox' ||
      !e.matches('input:not([type]),input[type="text"],input[type="search"],button[type="button"]')) return null;
  if (eligibility) return e.getAttribute('aria-expanded') === 'false' &&
    ![...document.querySelectorAll('[role="combobox"][aria-expanded="true"]')].some(other => other !== e);
  const id = e.getAttribute('aria-controls');
  const lists = [...document.querySelectorAll('[role="listbox"]')].filter(l => l.id === id);
  const users = [...document.querySelectorAll('[role="combobox"]')].filter(c => c.getAttribute('aria-controls') === id);
  if (!id || lists.length !== 1 || users.length !== 1 || e.getAttribute('aria-expanded') !== 'true' || !visible(lists[0])) return null;
  const list = lists[0], choices = [...list.querySelectorAll('[role="option"]')];
  if (!choices.length) return null;
  const options = choices.map(o => (o.getAttribute('aria-label') || o.textContent || '').trim());
  const valid = choices.length <= 50 && choices.every(o => visible(o) && o.getAttribute('aria-disabled') !== 'true') &&
    list.getAttribute('aria-multiselectable') !== 'true' && options.every(s => s && s.length <= 200) &&
    new Set(options.map(s => s.toLowerCase())).size === options.length;
  if (!valid) return {options: [], error: 'Ambiguous, disabled or unsupported dropdown choices'};
  list.setAttribute('data-aa-options', key);
  return {options, error: null};
}
