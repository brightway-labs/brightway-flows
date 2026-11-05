import {appendTriage, currentTriage, validStore} from './curation-package-state.mjs';

function initializePackages() {
// History restoration replaces the workspace contents, keeping its outer node.
// Bind to a child that is replaced so restored controls are initialized as well.
const binding = document.querySelector('[data-package-form], [data-triage-filter]');
if (!binding || binding.dataset.triageInitialized) return;
binding.dataset.triageInitialized = 'true';
const storageKey = 'brightway-curation-package-triage-v1';
let records = {};
let writable = true;
const message = document.querySelector('[data-triage-message]');
function report(text) { if (message) message.textContent = text; }
try {
  records = JSON.parse(localStorage.getItem(storageKey) || '{}');
  if (!validStore(records)) throw Error();
} catch (_) {
  writable = false; records = {};
  report('Existing browser triage could not be read. It has been preserved; saving is disabled.');
}
const filter = document.querySelector('[data-triage-filter]');
function paintPackages() {
  let acknowledged = 0;
  let visible = 0;
  for (const card of document.querySelectorAll('[data-package-row]')) {
    const status = currentTriage(records[card.dataset.packageRow] || [], card.dataset.packageRevision);
    card.querySelector('[data-package-status]').textContent = status.label;
    card.querySelector('[data-package-exceptions]').textContent = status.exceptions.length ? `${status.exceptions.length} individual exceptions remain to review` : '';
    const wanted = filter?.value || 'all';
    card.hidden = wanted === 'attention' ? !status.attention : wanted === 'acknowledged' ? status.state !== 'acknowledged' : wanted === 'split' ? status.state !== 'split' : false;
    if (!card.hidden) { visible += 1; if (status.state === 'acknowledged') acknowledged += 1; }
  }
  const visibleCount = document.querySelector('[data-package-visible-count]');
  if (visibleCount) visibleCount.textContent = String(visible);
  const empty = document.querySelector('[data-triage-empty]');
  if (empty) empty.hidden = visible > 0 || !document.querySelector('[data-package-row]');
  const count = document.querySelector('[data-triaged-count]');
  if (count) count.textContent = String(acknowledged);
}
if (filter) {
  document.querySelector('[data-triage-filter-label]').hidden = false;
  filter.addEventListener('change', paintPackages);
}
paintPackages();

for (const button of document.querySelectorAll('[data-export-triage]')) {
  button.hidden = !writable;
  button.addEventListener('click', () => {
    let stored;
    try {
      stored = JSON.parse(localStorage.getItem(storageKey) || '{}');
      if (!validStore(stored)) throw Error();
    } catch (_) { report('Existing triage could not be read; export was stopped.'); return; }
    const payload = {schema: 'curation-package-triage/1', exported_at: new Date().toISOString(), scope: 'personal-browser-triage', packages: stored};
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], {type: 'application/json'}));
    const link = document.createElement('a'); link.href = url; link.download = 'curation-package-triage.json';
    link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
}
const source = document.getElementById('curation-package-manifest');
if (source) {
  const manifest = JSON.parse(source.textContent);
  const memberNames = new Map(manifest.members.map(member => [member.id, member.title]));
  const form = document.querySelector('[data-package-form]');
  document.querySelector('[data-package-form-panel]').hidden = false;
  let exceptions = [];
  const latest = (records[manifest.id] || []).at(-1);
  if (latest) {
    form.elements.reviewer.value = latest.reviewer;
    exceptions = latest.exceptions.filter(id => memberNames.has(id));
  }
  function renderExceptions() {
    const list = document.querySelector('[data-exception-list]'); list.replaceChildren();
    for (const id of exceptions) {
      const item = document.createElement('li');
      const link = document.createElement('a'); link.href = `/curation/cases/${encodeURIComponent(id)}`; link.textContent = memberNames.get(id);
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'curation-reset'; remove.textContent = 'Remove exception';
      remove.addEventListener('click', () => { exceptions = exceptions.filter(value => value !== id); renderExceptions(); });
      item.append(link, remove); list.append(item);
    }
    if (!exceptions.length) { const item = document.createElement('li'); item.textContent = 'No individual exceptions selected.'; list.append(item); }
  }
  function renderHistory() {
    const events = records[manifest.id] || [];
    const status = currentTriage(events, manifest.revision);
    document.querySelector('[data-current-triage]').textContent = status.label;
    document.querySelector('[data-triage-context]').textContent = status.state === 'stale' ? 'Package scope or evidence changed. Earlier triage remains below; review this version before acknowledging it.' : 'This disposition concerns intake and next steps. Individual case quality stages remain unchanged.';
    const panel = document.querySelector('[data-package-history-panel]'); panel.hidden = !events.length;
    const list = document.querySelector('[data-package-history]'); list.replaceChildren();
    for (const event of [...events].reverse()) {
      const li = document.createElement('li'); const body = document.createElement('div');
      const heading = document.createElement('strong'); heading.textContent = `${event.reviewer} · ${event.decision}`;
      const date = document.createElement('small'); date.textContent = `${event.recorded_at} · ${event.member_count} records · ${event.exceptions.length} exceptions${event.revision === manifest.revision ? '' : ' · earlier evidence'}`;
      const note = document.createElement('p'); note.textContent = event.note;
      body.append(heading, date, note); li.append(body); list.append(li);
    }
  }
  document.querySelector('[data-import-exceptions]').addEventListener('click', () => {
    try {
      const personal = JSON.parse(localStorage.getItem('brightway-curation-personal-v1') || '{"saved":[]}');
      if (!Array.isArray(personal.saved)) throw Error();
      exceptions = [...new Set([...exceptions, ...personal.saved.filter(id => memberNames.has(id))])];
      renderExceptions(); report(`${exceptions.length} exceptions selected. Save a triage record to retain this decision.`);
    } catch (_) { report('The shortlist could not be read; no exceptions were changed.'); }
  });
  form.addEventListener('submit', event => {
    event.preventDefault();
    if (!writable) return;
    try {
      const stored = JSON.parse(localStorage.getItem(storageKey) || '{}');
      if (!validStore(stored)) throw Error('Existing triage could not be validated. Nothing was overwritten.');
      const events = appendTriage(stored[manifest.id] || [], manifest, {reviewer: form.elements.reviewer.value,
        decision: form.elements.decision.value, note: form.elements.note.value, exceptions}, new Date().toISOString());
      const next = {...stored, [manifest.id]: events};
      localStorage.setItem(storageKey, JSON.stringify(next)); records = next;
      renderHistory(); report('Triage recorded in this browser. Export it from the package list when you want a portable copy.');
    } catch (error) { report(error.message || 'Browser storage unavailable; this triage record was not saved.'); }
  });
  if (!writable) form.querySelector('button[type=submit]').disabled = true;
  renderExceptions(); renderHistory();
}

}
initializePackages();
document.addEventListener("curation:render", initializePackages);
