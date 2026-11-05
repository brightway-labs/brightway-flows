/* Triage describes an intake decision; it never changes a case's scientific state. */
const decisions = new Set(['acknowledged', 'investigate', 'split', 'reopened']);

export function currentTriage(events, revision) {
  const latest = events.at(-1);
  if (!latest) return {state: 'unreviewed', label: 'Unreviewed', exceptions: [], attention: true};
  if (latest.revision !== revision) return {state: 'stale', label: 'Changed · review again', exceptions: latest.exceptions, attention: true};
  const labels = {acknowledged: 'Acknowledged for triage', investigate: 'Needs investigation', split: 'Split requested', reopened: 'Reopened'};
  return {state: latest.decision, label: labels[latest.decision], exceptions: latest.exceptions,
    attention: latest.decision !== 'acknowledged' || latest.exceptions.length > 0};
}

export function appendTriage(events, manifest, input, recordedAt) {
  if (!decisions.has(input.decision) || !input.reviewer.trim() || !input.note.trim()) throw Error('Enter your name, a disposition and the reason for it.');
  if (!/^[a-f0-9]{64}$/.test(manifest.revision) || !Number.isFinite(Date.parse(recordedAt))) throw Error('A valid package fingerprint and timestamp are required.');
  const members = new Set(manifest.members.map(member => member.id));
  const exceptions = [...new Set(input.exceptions)].sort();
  if (exceptions.some(id => !members.has(id))) throw Error('Every exception must belong to this package.');
  return [...events, {package_id: manifest.id, title: manifest.title, revision: manifest.revision,
    member_count: members.size, member_ids: [...members].sort(), scope: 'package-intake', decision: input.decision,
    reviewer: input.reviewer.trim(), note: input.note.trim(), exceptions, recorded_at: recordedAt}];
}

export function validStore(store) {
  return !!store && typeof store === 'object' && !Array.isArray(store) && Object.values(store).every(events =>
    Array.isArray(events) && events.every(event => event.scope === 'package-intake' && decisions.has(event.decision)
      && typeof event.reviewer === 'string' && !!event.reviewer.trim() && typeof event.note === 'string'
      && !!event.note.trim() && /^[a-f0-9]{64}$/.test(event.revision)
      && Number.isFinite(Date.parse(event.recorded_at)) && Array.isArray(event.exceptions)
      && Array.isArray(event.member_ids) && event.member_ids.every(id => typeof id === 'string')
      && event.member_count === event.member_ids.length
      && event.exceptions.every(id => typeof id === 'string')));
}
