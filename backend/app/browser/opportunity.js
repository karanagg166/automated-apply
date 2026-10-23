() => {
  // Explicit public description landmarks only; never fall back to body text,
  // form values, JSON-LD, scripts, hidden content, cookies or account areas.
  const extract = selectors => {
    const nodes = [...document.querySelectorAll(selectors)].filter(e =>
      e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden' &&
      !e.closest('form,[contenteditable],nav,header,footer') &&
      !e.querySelector('form,input,textarea,select,[contenteditable]'));
    const texts = [...new Set(nodes.map(e => e.innerText.trim()).filter(Boolean))];
    return texts.length === 1 ? texts[0].slice(0,4000) : texts.length ? '' : null;
  };
  const section = names => {
    const normalize = text => text.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
    const parts = [];
    const seen = new Set();
    for (const heading of document.querySelectorAll('h2,h3,h4')) {
      if (!names.includes(normalize(heading.innerText)) || !heading.getClientRects().length ||
          heading.closest('form,[contenteditable],nav,header,footer')) continue;
      const name = normalize(heading.innerText);
      if (seen.has(name)) return '';
      seen.add(name);
      const root = heading.closest('main,article,section') || heading.parentElement;
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
      walker.currentNode = heading;
      let node;
      while ((node = walker.nextNode())) {
        if (/^H[1-6]$/.test(node.tagName) && +node.tagName[1] <= +heading.tagName[1]) break;
        if (!['P','LI'].includes(node.tagName) || !node.getClientRects().length ||
            getComputedStyle(node).visibility === 'hidden' ||
            node.closest('form,[contenteditable],nav,header,footer') ||
            node.querySelector('form,input,textarea,select,label,[contenteditable],[hidden],[aria-hidden="true"]') ||
            [...node.querySelectorAll('*')].some(child => getComputedStyle(child).display === 'none' || getComputedStyle(child).visibility === 'hidden')) continue;
        const text = node.innerText.trim();
        if (text && !parts.includes(text)) parts.push(text);
      }
    }
    return parts.join('\n').slice(0,4000);
  };
  const job = extract('[data-job-description],[itemprop="description"],#job-description,.job-description');
  const company = extract('[data-company-description],#company-description,.company-description');
  return {
    job_text: job === null ? section(['job description','about the role','role overview','the role','responsibilities','what you will do']) : job,
    company_text: company === null ? section(['about us','about the company','who we are','our company','our mission']) : company,
  };
}
