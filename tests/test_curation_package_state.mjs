import assert from 'node:assert/strict';
import {test} from 'node:test';
import {appendTriage, currentTriage, validStore} from '../src/brightway_flows/webapps/app/static/curation-package-state.mjs';

const manifest = {id:'test-package', title:'Test package', revision:'a'.repeat(64), members:[{id:'case-one'}, {id:'case-two'}]};
const input = {decision:'acknowledged', reviewer:'Test reviewer', note:'Test scope and next step', exceptions:['case-two']};
const stamp = '2026-10-13T15:00:00Z';

test('acknowledging a package retains individually held exceptions and exact membership', () => {
  const history = [];
  const result = appendTriage(history, manifest, input, stamp);
  assert.equal(history.length, 0);
  assert.deepEqual(result[0].member_ids, ['case-one', 'case-two']);
  assert.equal(result[0].scope, 'package-intake');
  const status = currentTriage(result, manifest.revision);
  assert.equal(status.state, 'acknowledged');
  assert.equal(status.attention, true);
  assert.deepEqual(status.exceptions, ['case-two']);
  assert.equal(validStore({'test-package':result}), true);
  assert.equal('signoffs' in result[0], false);
});

test('changed package evidence reopens triage and retains earlier decisions', () => {
  const first = appendTriage([], manifest, input, stamp);
  const nextManifest = {...manifest, revision:'b'.repeat(64)};
  assert.equal(currentTriage(first, nextManifest.revision).state, 'stale');
  const second = appendTriage(first, nextManifest, {...input, decision:'split'}, stamp);
  assert.equal(second.length, 2);
  assert.deepEqual(second[0], first[0]);
  assert.equal(currentTriage(second, nextManifest.revision).state, 'split');
  assert.equal(currentTriage(second, manifest.revision).state, 'stale');
});

test('triage refuses fabricated approval states, unknown exceptions and missing attribution', () => {
  for (const change of [{decision:'scientifically-approved'}, {exceptions:['foreign-case']}, {reviewer:' '}, {note:''}]) {
    assert.throws(() => appendTriage([], manifest, {...input, ...change}, stamp));
  }
  assert.equal(currentTriage([], manifest.revision).state, 'unreviewed');
  assert.equal(validStore({'test-package':[{decision:'acknowledged'}]}), false);
});
