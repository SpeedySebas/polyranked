const test = require('node:test');
const assert = require('node:assert/strict');
const { diagnose, stepText } = require('../site/update-diagnostics.js');
const now = Date.parse('2026-10-01T03:20:00Z');
const completed = {run_number:12,status:'completed',conclusion:'success',event:'push',created_at:'2026-10-01T03:10:00Z'};
test('a missing scheduled run is distinguished from a running script', () => {
    assert.match(diagnose([completed], now), /No newer run is reported.*03:17:00 UTC/);
    assert.match(diagnose([{...completed,status:'queued',conclusion:null}], now), /is queued/);
    assert.match(diagnose([{...completed,status:'in_progress',conclusion:null}], now), /is in progress/);
});
test('recent failures point to the failed step instead of claiming success', () => {
    assert.match(diagnose([{...completed,created_at:'2026-10-01T03:18:00Z',conclusion:'failure'}], now), /failed step and error/);
});
test('step timing displays elapsed running time and fixed completed duration', () => {
    const step={name:'Fetch rankings',status:'in_progress',started_at:'2026-10-01T03:19:30Z'};
    assert.match(stepText(step,now), /30s/);
    assert.match(stepText({...step,status:'completed',conclusion:'success',completed_at:'2026-10-01T03:19:45Z'},now), /15s/);
    assert.doesNotMatch(stepText({name:'Publish',status:'pending'},now), /NaN/);
});
