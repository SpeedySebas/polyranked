(function (root) {
    'use strict';
    const API = 'https://api.github.com/repos/SpeedySebas/polyranked';
    const RUN_URL = 'https://github.com/SpeedySebas/polyranked/actions/runs/';
    const utc = value => value && Number.isFinite(Date.parse(value)) ? new Date(value).toISOString().replace('T', ' ').replace(/\.\d{3}Z$/, ' UTC') : 'not reported';
    const label = run => (run.conclusion || run.status || 'unknown').replaceAll('_', ' ');
    function diagnose(runs, now) {
        if (!runs.length) return 'GitHub has not reported any runs for the main publisher.';
        const active = runs.find(run => run.status !== 'completed');
        if (active) return `Cloud run #${active.run_number} is ${label(active)}. See its steps below.`;
        const latest = runs[0];
        const scheduledStart = Math.floor((now - 120000) / 300000) * 300000 + 120000;
        const missed = Date.parse(latest.created_at) < scheduledStart && now - scheduledStart > 60000;
        const outcome = `Latest cloud run #${latest.run_number}: ${label(latest)} (${latest.event}, started ${utc(latest.created_at)}).`;
        if (missed) return `${outcome} No newer run is reported for the scheduled start at ${utc(new Date(scheduledStart).toISOString())}; the script has not started for that slot as of this check.`;
        if (latest.conclusion === 'failure' || latest.conclusion === 'timed_out') return `${outcome} Inspect the failed step and error messages below. The previous successful website remains online.`;
        return `${outcome} The browser checks for published data every 15 seconds.`;
    }
    function stepText(step, now) {
        const started = Date.parse(step.started_at);
        const ended = Date.parse(step.completed_at);
        const duration = Number.isFinite(started) ? ` · ${Math.max(0, Math.round(((Number.isFinite(ended) ? ended : now) - started) / 1000))}s` : '';
        return `${step.name}: ${label(step)}${duration}${step.started_at ? ' · started ' + utc(step.started_at) : ''}${step.completed_at ? ' · finished ' + utc(step.completed_at) : ''}`;
    }
    if (typeof module !== 'undefined' && module.exports) module.exports = { diagnose, stepText, utc };
    if (typeof document === 'undefined') return;
    const el = id => document.getElementById(id);
    const panel = el('update-logs');
    const browserLog = [];
    root.rankingDiagnostics = {
        log(message) {
            browserLog.unshift(`${utc(new Date().toISOString())}  ${message}`);
            browserLog.length = Math.min(browserLog.length, 120);
            el('browser-update-log').textContent = browserLog.join('\n');
        },
    };
    let busy = false, lastCheck = 0, blockedUntil = 0, selected = null, pinned = false, runs = [];
    const detailsCache = new Map();
    async function get(path) {
        if (Date.now() < blockedUntil) throw new Error(`GitHub's public request limit was reached. Try again after ${utc(new Date(blockedUntil).toISOString())}.`);
        const response = await fetch(API + path, { headers: { Accept: 'application/vnd.github+json' }, cache: 'no-cache', signal: AbortSignal.timeout(20000) });
        const remaining = response.headers.get('x-ratelimit-remaining');
        if (remaining !== null && Number(remaining) <= 3) {
            blockedUntil = Math.max(Date.now() + 180000, Number(response.headers.get('x-ratelimit-reset')) * 1000 + 1000);
        }
        if (!response.ok) throw new Error(`GitHub status request returned HTTP ${response.status}${blockedUntil > Date.now() ? '; public request limit reached' : ''}. Ranking updates are unaffected.`);
        return response.json();
    }
    function listItem(parent, text) {
        const item = document.createElement('li');
        item.textContent = text;
        parent.append(item);
        return item;
    }
    async function showRun(run) {
        selected = run.id;
        el('cloud-step-heading').textContent = `Steps for run #${run.run_number}`;
        el('cloud-steps').textContent = 'Loading run details…';
        el('cloud-messages').textContent = 'Loading reported messages…';
        const cached = detailsCache.get(run.id);
        let detail;
        if (cached && cached.updated_at === run.updated_at && run.status === 'completed') {
            detail = cached;
        } else {
            const result = await get(`/actions/runs/${run.id}/jobs?per_page=10`);
            const jobs = result.jobs || [];
            const messages = [];
            for (const job of jobs) {
                if (!Number.isSafeInteger(job.id)) continue;
                const notes = await get(`/check-runs/${job.id}/annotations?per_page=100`);
                for (const note of notes) messages.push(`[${note.annotation_level || 'message'}] ${note.title ? note.title + ': ' : ''}${note.message || ''}`);
            }
            detail = { jobs, messages, updated_at: run.updated_at };
            detailsCache.set(run.id, detail);
            if (detailsCache.size > 10) detailsCache.delete(detailsCache.keys().next().value);
        }
        if (selected !== run.id) return;
        el('cloud-steps').textContent = '';
        if (!detail.jobs.length) listItem(el('cloud-steps'), 'No runner has started this job yet.');
        for (const job of detail.jobs) {
            for (const step of job.steps || []) listItem(el('cloud-steps'), stepText(step, Date.now()));
        }
        el('cloud-messages').textContent = detail.messages.length ? detail.messages.join('\n\n') : 'No messages reported yet. Script messages can appear after the current step finishes; use the full run log for console output.';
    }
    function renderRuns() {
        el('cloud-runs').textContent = '';
        for (const run of runs) {
            const item = listItem(el('cloud-runs'), '');
            const button = document.createElement('button');
            button.type = 'button';
            button.textContent = `#${run.run_number} · ${run.event} · ${label(run)}`;
            button.addEventListener('click', () => inspect(run));
            const link = document.createElement('a');
            link.href = RUN_URL + run.id;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            link.textContent = ' Full log ↗';
            item.append(button, document.createTextNode(' · ' + utc(run.created_at) + ' '), link);
        }
    }
    async function inspect(run) {
        if (busy) return;
        pinned = true;
        busy = true;
        el('refresh-cloud-logs').disabled = true;
        try { await showRun(run); }
        catch (error) { el('cloud-messages').textContent = `Could not load run details: ${error.message}`; }
        finally { busy = false; el('refresh-cloud-logs').disabled = false; }
    }
    async function refresh() {
        if (busy || Date.now() - lastCheck < 15000) return;
        busy = true;
        lastCheck = Date.now();
        el('refresh-cloud-logs').disabled = true;
        try {
            const result = await get('/actions/workflows/update_leaderboard.yml/runs?per_page=8');
            runs = (result.workflow_runs || []).filter(run => Number.isSafeInteger(run.id));
            el('cloud-diagnosis').textContent = diagnose(runs, Date.now());
            el('cloud-checked').textContent = `Run history last checked: ${utc(new Date().toISOString())}. This is a status snapshot, not a live console stream.`;
            renderRuns();
            const run = (pinned && runs.find(item => item.id === selected)) || runs[0];
            if (run) await showRun(run);
        } catch (error) {
            el('cloud-messages').textContent = `Could not refresh cloud diagnostics: ${error.message}\nPreviously displayed cloud status may be out of date. Use the GitHub link above. This does not stop ranking refreshes.`;
        } finally {
            busy = false;
            el('refresh-cloud-logs').disabled = false;
        }
    }
    panel.addEventListener('toggle', () => { if (panel.open) refresh(); });
    el('refresh-cloud-logs').addEventListener('click', refresh);
    setInterval(() => { if (panel.open && !document.hidden) refresh(); }, 180000);
})(typeof globalThis !== 'undefined' ? globalThis : this);
