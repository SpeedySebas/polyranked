const test = require('node:test');
const assert = require('node:assert/strict');
const { LiveUpdater, nextRelease, countdown } = require('../site/live-updates.js');
const at = time => Date.parse(`2026-09-30T${time}Z`);
const descriptor = (version, generated, release) => ({version, generated_at: new Date(at(generated)).toISOString(), release_at: new Date(at(release)).toISOString()});
const old = descriptor('old', '12:00:00', '12:07:00');
const fresh = descriptor('new', '12:28:00', '12:37:00');
function fixture() {
    let now = at('12:30:00');
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
    assert.equal(f.states.at(-1).text,'Next update in 07:00'); assert.equal(f.states.at(-1).ready,true);
    f.offline(); f.time('12:36:59'); f.updater.tick(); assert.deepEqual(f.applied,['old']);
    f.time('12:37:00'); f.updater.tick(); assert.deepEqual(f.applied,['old','new']);
    assert.deepEqual(f.loaded,['old','new']); assert.equal(f.states.at(-1).text,'Scheduled update in 30:00');
});
test('a late build preserves the old rankings and waits instead of resetting the timer', async () => {
    const f=fixture(); f.manifest([old]); await f.updater.refresh(); f.time('12:37:00'); f.updater.tick();
    assert.equal(f.states.at(-1).state,'waiting'); assert.deepEqual(f.applied,['old']);
    f.time('12:38:12'); f.updater.tick();
    assert.equal(f.states.at(-1).text,'Update delayed 01:12 · checking…');
    f.time('12:39:00'); f.manifest([old,fresh]); await f.updater.refresh();
    assert.deepEqual(f.applied,['old','new']); assert.equal(f.states.at(-1).text,'Scheduled update in 28:00');
});
test('unprepared targets are identified as scheduled and offline retries stay visible', async () => {
    const f=fixture(); f.manifest([old]); await f.updater.refresh();
    assert.equal(f.states.at(-1).text,'Scheduled update in 07:00');
    f.offline(); f.time('12:39:00'); await f.updater.refresh();
    assert.equal(f.states.at(-1).text,'Update delayed 02:00 · reconnecting…');
    assert.deepEqual(f.applied,['old']);
});
test('opening the page after the boundary loads the released version', async () => {
    const f=fixture(); f.time('12:40:00'); await f.updater.refresh(); assert.equal(f.applied.at(-1),'new');
});
test('older manifests cannot roll displayed rankings backwards', async () => {
    const f=fixture(); f.time('12:40:00'); await f.updater.refresh(); f.manifest([old]); await f.updater.refresh();
    assert.deepEqual(f.applied,['new']);
});
test('waking a background tab applies prefetched data immediately', async () => {
    const f=fixture(); await f.updater.refresh(); f.time('12:45:00'); f.updater.tick(); assert.equal(f.applied.at(-1),'new');
});
test('release cadence crosses the hour and countdown never goes negative', () => {
    assert.equal(nextRelease(at('12:37:00')),at('13:07:00'));
    assert.equal(nextRelease(at('12:07:00')),at('12:37:00'));
    assert.equal(countdown(-100),'00:00'); assert.equal(countdown(1),'00:01');
});
test('one-minute cloud mode prefetches each queued snapshot and returns to normal after expiry', async () => {
    const f=fixture();
    const minute1={...descriptor('minute1','12:29:30','12:31:00'), interval_seconds:60, test_until:new Date(at('12:34:00')).toISOString()};
    const minute2={...descriptor('minute2','12:30:30','12:32:00'), interval_seconds:60, test_until:minute1.test_until};
    f.manifest([old,minute1,minute2]); await f.updater.refresh();
    assert.deepEqual(f.loaded,['old','minute1','minute2']);
    assert.equal(f.states.at(-1).text,'Test update in 01:00');
    f.offline(); f.time('12:31:00'); f.updater.tick();
    assert.deepEqual(f.applied,['old','minute1']);
    assert.equal(f.states.at(-1).text,'Test update in 01:00');
    f.time('12:32:00'); f.updater.tick();
    assert.deepEqual(f.applied,['old','minute1','minute2']);
    f.time('12:33:04'); f.updater.tick();
    assert.equal(f.states.at(-1).text,'Update delayed 00:04 · checking…');
    f.time('12:34:00'); f.updater.tick();
    assert.equal(f.states.at(-1).text,'Scheduled update in 03:00');
});
