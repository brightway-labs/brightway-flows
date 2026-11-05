/* htmx owns transport, swaps and history; this adapter owns input timing. */
(() => {
  let timer;
  let generation = 0;
  let tablePosition;
  const form = () => document.getElementById('curation-filter-form');
  function changed() {
    clearTimeout(timer);
    generation += 1;
    const workspace = document.getElementById('curation-workspace');
    if (workspace && window.htmx) htmx.trigger(workspace, 'htmx:abort');
  }
  function apply() {
    clearTimeout(timer);
    const current = form();
    if (current && window.htmx) htmx.trigger(current, 'curation-filter');
  }
  function belongs(target) { return target?.form === form() && !!form(); }
  document.addEventListener('input', event => {
    if (!belongs(event.target) || event.target.type !== 'search') return;
    changed();
    if (!event.isComposing) timer = setTimeout(apply, 250);
  });
  document.addEventListener('compositionstart', event => { if (belongs(event.target)) changed(); });
  document.addEventListener('compositionend', event => { if (belongs(event.target)) { changed(); timer = setTimeout(apply, 250); } });
  document.addEventListener('change', event => {
    if (!belongs(event.target) || event.target.tagName !== 'SELECT') return;
    changed(); apply();
  });
  document.addEventListener('submit', event => {
    if (event.target === form()) changed();
  }, true);
  document.addEventListener('click', event => {
    if (event.target.closest('[data-filter-retry]')) { changed(); apply(); }
    if (event.target.closest('#curation-workspace a[href]')) changed();
  }, true);
  window.addEventListener('popstate', changed);
  document.addEventListener('htmx:configRequest', event => {
    if (!event.detail.elt.closest('#curation-workspace')) return;
    // Keep URLs readable. Empty grouping is meaningful; other empty filters are not.
    for (const [key, value] of Object.entries(event.detail.parameters)) {
      if (value === '' && key !== 'group') delete event.detail.parameters[key];
    }
  });
  document.addEventListener('htmx:beforeRequest', event => {
    if (!event.detail.elt.closest('#curation-workspace')) return;
    event.detail.xhr.curationGeneration = generation;
    document.querySelector('[data-filter-error]')?.setAttribute('hidden', '');
    document.getElementById('curation-workspace')?.setAttribute('aria-busy', 'true');
  });
  document.addEventListener('htmx:beforeSwap', event => {
    const revision = event.detail.xhr.curationGeneration;
    if (revision !== undefined && revision !== generation) event.detail.shouldSwap = false;
    const scroll = document.querySelector('.curation-browser-panel .curation-table-scroll');
    tablePosition = scroll ? {kind: scroll.querySelector('table').className, left: scroll.scrollLeft} : null;
  });
  function render(event) {
    document.getElementById('curation-workspace')?.removeAttribute('aria-busy');
    const scroll = document.querySelector('.curation-browser-panel .curation-table-scroll');
    if (event?.type === 'htmx:afterSwap' && scroll?.querySelector('table').className === tablePosition?.kind) scroll.scrollLeft = tablePosition.left;
    tablePosition = null;
    document.dispatchEvent(new CustomEvent('curation:render'));
  }
  document.addEventListener('htmx:afterSwap', render);
  document.addEventListener('htmx:historyRestore', render);
  document.addEventListener('htmx:afterSettle', () => {
    const announcement = document.querySelector('[data-results-announcement]');
    if (announcement) announcement.textContent = document.querySelector('[data-results-summary]')?.textContent.trim() || '';
  });
  function failed(event) {
    if (event.detail.xhr?.curationGeneration !== generation) return;
    document.getElementById('curation-workspace')?.removeAttribute('aria-busy');
    document.querySelector('[data-filter-error]')?.removeAttribute('hidden');
  }
  for (const name of ['htmx:responseError', 'htmx:sendError', 'htmx:timeout']) document.addEventListener(name, failed);
  document.addEventListener('DOMContentLoaded', render);
})();
