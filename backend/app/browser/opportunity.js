() => {
  // Explicit public description landmarks only; never fall back to body text,
  // form values, JSON-LD, scripts, hidden content, cookies or account areas.
  const extract = selectors => {
    const nodes = [...document.querySelectorAll(selectors)].filter(e =>
      e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden' &&
      !e.closest('form,[contenteditable],nav,header,footer') &&
      !e.querySelector('form,input,textarea,select,[contenteditable]'));
    const texts = [...new Set(nodes.map(e => e.innerText.trim()).filter(Boolean))];
    return texts.length === 1 ? texts[0].slice(0,4000) : '';
  };
  return {
    job_text: extract('[data-job-description],[itemprop="description"],#job-description,.job-description'),
    company_text: extract('[data-company-description],#company-description,.company-description'),
  };
}
