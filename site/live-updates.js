(function (root) {
    'use strict';
    const PERIOD = 5 * 60 * 1000;
    const OFFSET = 0;
    const nextRelease = time => Math.floor((time - OFFSET) / PERIOD) * PERIOD + OFFSET + PERIOD;
    const countdown = milliseconds => {
        const seconds = Math.max(0, Math.ceil(milliseconds / 1000));
        return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
    };

    class LiveUpdater {
        constructor({ now = Date.now, loadManifest, loadSnapshot, applySnapshot, showStatus }) {
            Object.assign(this, { now, loadManifest, loadSnapshot, applySnapshot, showStatus });
            this.prepared = new Map();
            this.current = null;
            this.busy = false;
            this.failed = false;
        }

        async refresh() {
            if (this.busy) return;
            this.busy = true;
            try {
                const manifest = await this.loadManifest();
                if (manifest.schema !== 1 || !Array.isArray(manifest.snapshots) || !manifest.snapshots.length) throw new Error('Invalid update manifest');
                const ordered = manifest.snapshots.slice().sort((a, b) => Date.parse(a.generated_at) - Date.parse(b.generated_at));
                const due = ordered.filter(item => Date.parse(item.release_at) <= this.now()).at(-1);
                const future = ordered.filter(item => Date.parse(item.release_at) > this.now()).slice(-1);
                for (const descriptor of [due, ...future].filter(Boolean)) {
                    if (!Number.isFinite(Date.parse(descriptor.release_at)) || !Number.isFinite(Date.parse(descriptor.generated_at))) throw new Error('Invalid update timestamp');
                    if (this.current && Date.parse(descriptor.generated_at) <= Date.parse(this.current.generated_at)) continue;
                    if (!this.prepared.has(descriptor.version)) {
                        const payload = await this.loadSnapshot(descriptor);
                        if (!payload.datasets?.PLAYERS?.length || !payload.datasets?.TRACK_WEIGHTS_DATA?.length || payload.generated_at !== descriptor.generated_at) throw new Error('Incomplete ranking snapshot');
                        this.prepared.set(descriptor.version, { descriptor, payload });
                    }
                    this.tick();
                }
                this.failed = false;
            } catch (error) {
                this.failed = true;
                console.warn('Ranking refresh will retry:', error.message);
            } finally {
                this.busy = false;
                this.tick();
            }
        }

        tick() {
            const now = this.now();
            const eligible = [...this.prepared.values()].filter(({ descriptor }) => Date.parse(descriptor.release_at) <= now && (!this.current || Date.parse(descriptor.generated_at) > Date.parse(this.current.generated_at)));
            eligible.sort((a, b) => Date.parse(b.descriptor.generated_at) - Date.parse(a.descriptor.generated_at));
            if (eligible.length) {
                const ready = eligible[0];
                this.applySnapshot(ready.payload);
                this.current = ready.descriptor;
                for (const [version, { descriptor }] of this.prepared) if (Date.parse(descriptor.generated_at) <= Date.parse(this.current.generated_at)) this.prepared.delete(version);
            }
            if (!this.current) {
                this.showStatus({ state: 'loading', text: this.failed ? 'Unable to load rankings. Retrying…' : 'Loading the latest rankings…' });
                return;
            }
            const deadline = nextRelease(Math.max(Date.parse(this.current.release_at), Date.parse(this.current.generated_at)));
            const ready = [...this.prepared.values()].some(({ descriptor }) => Date.parse(descriptor.release_at) <= deadline);
            this.showStatus(now >= deadline
                ? { state: 'waiting', text: `Update delayed ${countdown(now - deadline)} · ${this.failed ? 'reconnecting…' : 'checking…'}`, deadline, ready: false }
                : { state: 'counting', text: `${ready ? 'Next' : 'Scheduled'} update in ${countdown(deadline - now)}`, deadline, ready });
        }
    }

    if (typeof module !== 'undefined' && module.exports) module.exports = { LiveUpdater, nextRelease, countdown };
    if (typeof document === 'undefined') return;

    const fetchFile = async (path, fresh = false) => {
        const url = new URL(path, window.location.href);
        if (fresh) url.searchParams.set('_', String(Date.now()));
        const response = await fetch(url, { cache: fresh ? 'no-store' : 'default', signal: AbortSignal.timeout(60000) });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response;
    };
    const updater = new LiveUpdater({
        loadManifest: async () => (await fetchFile('update.json', true)).json(),
        loadSnapshot: async descriptor => {
            if (!/^snapshots\/[a-f0-9]{64}\.json$/.test(descriptor.url)) throw new Error('Invalid snapshot URL');
            const bytes = await (await fetchFile(descriptor.url)).arrayBuffer();
            const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(value => value.toString(16).padStart(2, '0')).join('');
            if (digest !== descriptor.sha256) throw new Error('Snapshot integrity check failed');
            return JSON.parse(new TextDecoder().decode(bytes));
        },
        applySnapshot: snapshot => applyRankingSnapshot(snapshot),
        showStatus: status => {
            const badge = document.getElementById('update-countdown');
            badge.textContent = status.text;
            badge.dataset.state = status.state;
            badge.title = status.ready ? 'Fresh rankings are downloaded and ready to appear when the timer reaches zero.'
                : status.state === 'waiting' ? 'The cloud update is late. Checking every 15 seconds; fresh rankings will appear automatically. The last-updated time still describes the displayed data.'
                : 'Updates are scheduled every five minutes (:00, :05, :10, and so on). GitHub may delay scheduled builds. The next data is not downloaded yet.';
            if (status.state === 'loading') document.getElementById('loading-state').textContent = status.text;
        },
    });
    updater.refresh();
    setInterval(() => updater.tick(), 250);
    setInterval(() => updater.refresh(), 15000);
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) { updater.tick(); updater.refresh(); }
    });
    window.addEventListener('online', () => updater.refresh());
})(typeof globalThis !== 'undefined' ? globalThis : this);
