const test = require('node:test');
const assert = require('node:assert/strict');
const { LiveUpdater, nextRelease, countdown } = require('../site/live-updates.js');
const at = time => Date.parse(`2026-09-30T${time}Z`);
const descriptor = (version, generated, release) => ({version, generated_at: new Date(at(generated)).toISOString(), release_at: new Date(at(release)).toISOString()});
const old = descriptor('old', '12:27:30', '12:30:00');
const fresh = descriptor('new', '12:32:30', '12:35:00');
function fixture() {
    let now = at('12:33:00');
    let snapshots = [old, fresh];
    let offline = false;
    const applied = [], loaded = [], states = [];
    const updater = new LiveUpdater({
        now: () => now,
        loadManifest: async () => { if (offline) throw new Error('offline'); return {schema:1,snapshots}; },
        loadSnapshot: async item => { loaded.push(item.version); return {generated_at:item.generated_at, datasets:{PLAYERS:[{u:item.version}],TRACK_WEIGHTS_DATA:[{}]}}; },
        applySnapshot: payload => applied.push(payload.datasets.PLAYERS[0].u),
        showStatus: status => states.push(status),
    });
    return {updater, applied, loaded, states, time: value => now=at(value), manifest: value => snapshots=value, offline: () => offline=true};
}
test('downloads and parses the next data before zero, then swaps without a fetch', async () => {
    const f = fixture(); await f.updater.refresh();
    assert.deepEqual(f.loaded,['old','new']); assert.deepEqual(f.applied,['old']);
    assert.equal(f.states.at(-1).text,'Next update in 02:00'); assert.equal(f.states.at(-1).ready,true);
    f.offline(); f.time('12:34:59'); f.updater.tick(); assert.deepEqual(f.applied,['old']);
    f.time('12:35:00'); f.updater.tick(); assert.deepEqual(f.applied,['old','new']);
    assert.deepEqual(f.loaded,['old','new']); assert.equal(f.states.at(-1).text,'Scheduled update in 05:00');
});
test('a late build preserves the old rankings and waits instead of resetting the timer', async () => {
    const f=fixture(); f.manifest([old]); await f.updater.refresh(); f.time('12:35:00'); f.updater.tick();
    assert.equal(f.states.at(-1).state,'waiting'); assert.deepEqual(f.applied,['old']);
    f.time('12:36:12'); f.updater.tick();
    assert.equal(f.states.at(-1).text,'Update delayed 01:12 · checking…');
    f.time('12:37:00'); f.manifest([old,fresh]); await f.updater.refresh();
    assert.deepEqual(f.applied,['old','new']); assert.equal(f.states.at(-1).text,'Scheduled update in 03:00');
});
test('unprepared targets are identified as scheduled and offline retries stay visible', async () => {
    const f=fixture(); f.manifest([old]); await f.updater.refresh();
    assert.equal(f.states.at(-1).text,'Scheduled update in 02:00');
    f.offline(); f.time('12:37:00'); await f.updater.refresh();
    assert.equal(f.states.at(-1).text,'Update delayed 02:00 · reconnecting…');
    assert.deepEqual(f.applied,['old']);
});
test('opening the page after the boundary loads the released version', async () => {
    const f=fixture(); f.time('12:38:00'); await f.updater.refresh(); assert.equal(f.applied.at(-1),'new');
});
test('older manifests cannot roll displayed rankings backwards', async () => {
    const f=fixture(); f.time('12:38:00'); await f.updater.refresh(); f.manifest([old]); await f.updater.refresh();
    assert.deepEqual(f.applied,['new']);
});
test('waking a background tab applies prefetched data immediately', async () => {
    const f=fixture(); await f.updater.refresh(); f.time('12:40:00'); f.updater.tick(); assert.equal(f.applied.at(-1),'new');
});
test('release cadence crosses the hour and countdown never goes negative', () => {
    assert.equal(nextRelease(at('12:55:00')),at('13:00:00'));
    assert.equal(nextRelease(at('12:00:00')),at('12:05:00'));
    assert.equal(countdown(-100),'00:00'); assert.equal(countdown(1),'00:01');
});
