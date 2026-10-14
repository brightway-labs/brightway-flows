/* Browser-local personal organisation. Delegation survives result updates. */
(() => {
  const key = 'brightway-curation-personal-v1';
  function read() {
    try {
      const data = JSON.parse(localStorage.getItem(key) || '{"saved":[],"notes":{}}');
      if (Array.isArray(data.saved) && data.notes && typeof data.notes === 'object') return data;
    } catch (_) {}
    return {saved: [], notes: {}};
  }
  let personal = read();
  function persist() {
    const status = document.querySelector('[data-note-status]');
    try { localStorage.setItem(key, JSON.stringify(personal)); if (status) status.textContent = 'Saved in this browser.'; }
    catch (_) { if (status) status.textContent = 'Browser storage unavailable. This note lasts only for this page.'; }
  }
  function paint() {
    const savedOnly = !!new URL(location.href).searchParams.get('saved');
    document.querySelectorAll('[data-save-case]').forEach(button => {
      const saved = personal.saved.includes(button.dataset.saveCase);
      button.hidden = false;
      button.setAttribute('aria-pressed', String(saved));
      button.textContent = button.classList.contains('curation-save') ? saved ? '★' : '☆' : saved ? 'Saved to my shortlist' : 'Save to my shortlist';
    });
    document.querySelectorAll('[data-shortlist-count]').forEach(node => node.textContent = personal.saved.length);
    const filter = document.querySelector('[data-shortlist-filter]');
    if (filter) { filter.hidden = false; filter.setAttribute('aria-pressed', String(savedOnly)); }
    const note = document.querySelector('[data-note-case]');
    if (note && !note.dataset.initialized) {
      note.dataset.initialized = 'true';
      document.querySelector('[data-local-notes]').hidden = false;
      note.value = typeof personal.notes[note.dataset.noteCase] === 'string' ? personal.notes[note.dataset.noteCase] : '';
    }
  }
  function applyShortlist(wanted) {
    const form = document.getElementById('curation-filter-form');
    if (form && window.htmx) {
      form.elements.saved.value = wanted ? personal.saved.join(',') || 'no-saved-cases' : '';
      form.requestSubmit();
    } else {
      const url = new URL(location.href); url.searchParams.delete('page');
      if (wanted) url.searchParams.set('saved', personal.saved.join(',') || 'no-saved-cases'); else url.searchParams.delete('saved');
      location.assign(url.href);
    }
  }
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-save-case]');
    if (button) {
      personal = read();
      const id = button.dataset.saveCase;
      personal.saved = personal.saved.includes(id) ? personal.saved.filter(item => item !== id) : [...personal.saved, id];
      persist(); paint();
      if (new URL(location.href).searchParams.get('saved')) applyShortlist(true);
    }
    if (event.target.closest('[data-shortlist-filter]')) applyShortlist(!new URL(location.href).searchParams.get('saved'));
    if (event.target.closest('[data-clear-note]')) {
      const note = document.querySelector('[data-note-case]');
      delete personal.notes[note.dataset.noteCase]; note.value = ''; persist();
    }
  });
  document.addEventListener('input', event => {
    const note = event.target.closest('[data-note-case]');
    if (note) { personal.notes[note.dataset.noteCase] = note.value; persist(); }
  });
  document.addEventListener('curation:render', paint);
  document.addEventListener('htmx:pushedIntoHistory', paint);
  paint();
})();
