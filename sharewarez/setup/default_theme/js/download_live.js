/* One visibility-aware transport for SSE and bounded, non-overlapping fallback. */
(() => {
    'use strict';
    window.DownloadLive = {
        connect({view, ids = [], poll, render, status}) {
            let source = null, timer = null, retry = null, watchdog = null;
            let controller = null, stopped = false, generation = 0, live = false;
            let delay = 2000;
            const report = message => { if (status) status(message); };
            const clear = () => {
                clearTimeout(timer); clearTimeout(retry); clearTimeout(watchdog);
                controller?.abort(); controller = null;
                source?.close(); source = null; live = false;
                generation++;
            };
            const pollOnce = async () => {
                if (stopped || document.hidden || live || controller) return;
                const version = generation;
                const pending = new AbortController();
                controller = pending;
                const timeout = setTimeout(() => pending.abort(), 10000);
                try {
                    const data = await poll(pending.signal);
                    if (version !== generation || stopped || document.hidden || live) return;
                    render(data);
                    delay = 2000;
                    report('Live connection unavailable · refreshing periodically');
                } catch (error) {
                    if (version === generation && !stopped && !document.hidden) {
                        delay = Math.min(delay * 2, 30000);
                        report('Connection interrupted · retrying');
                    }
                } finally {
                    clearTimeout(timeout);
                    if (controller === pending) controller = null;
                    if (version === generation && !stopped && !document.hidden && !live) {
                        timer = setTimeout(pollOnce, delay);
                    }
                }
            };
            const fallback = () => {
                if (stopped || document.hidden) return;
                clear();
                report('Reconnecting · periodic updates enabled');
                pollOnce();
                retry = setTimeout(open, 30000);
            };
            const armWatchdog = milliseconds => {
                clearTimeout(watchdog);
                watchdog = setTimeout(fallback, milliseconds);
            };
            const open = () => {
                if (stopped || document.hidden) return;
                clear();
                report('Connecting live updates…');
                if (!window.EventSource) { fallback(); return; }
                const version = generation;
                const params = new URLSearchParams({view, ids: ids.join(',')});
                try { source = new EventSource(`/api/live/downloads?${params}`); }
                catch (_) { fallback(); return; }
                armWatchdog(5000);
                source.addEventListener('snapshot', event => {
                    if (version !== generation || stopped || document.hidden) return;
                    try {
                        const data = JSON.parse(event.data);
                        render(data);
                        live = true;
                        report('Live updates connected');
                        armWatchdog(25000);
                    } catch (_) { fallback(); }
                });
                source.addEventListener('access-revoked', () => {
                    clear(); stopped = true;
                    report('Session ended · reload to sign in');
                });
                source.onerror = () => { if (version === generation) fallback(); };
            };
            const visibility = () => {
                if (document.hidden) { clear(); report('Updates paused while hidden'); }
                else open();
            };
            const close = () => {
                stopped = true; clear();
                document.removeEventListener('visibilitychange', visibility);
                window.removeEventListener('pagehide', clear);
                window.removeEventListener('pageshow', restore);
            };
            const restore = event => { if (event.persisted) open(); };
            document.addEventListener('visibilitychange', visibility);
            window.addEventListener('pagehide', clear);
            window.addEventListener('pageshow', restore);
            open();
            return {close};
        },
        async json(url, signal) {
            const response = await fetch(url, {signal, credentials: 'same-origin', cache: 'no-store',
                headers: {'Accept': 'application/json'}});
            if (!response.ok) throw new Error(`Refresh failed (${response.status})`);
            return response.json();
        },
        text(node, value) {
            const text = String(value);
            if (!node || node.textContent === text) return;
            // Do not destroy text the user is selecting/copying during a refresh.
            const selection = window.getSelection();
            if (selection && !selection.isCollapsed && selection.containsNode(node, true)) return;
            node.textContent = text;
        },
        duration(value) {
            const seconds = Math.max(0, Math.floor(Number(value) || 0));
            const days = Math.floor(seconds / 86400), hours = Math.floor(seconds % 86400 / 3600);
            const minutes = Math.floor(seconds % 3600 / 60), remainder = seconds % 60;
            if (days) return `${days}d${hours ? ` ${hours}h` : ''}`;
            if (hours) return `${hours}h${minutes ? ` ${minutes}m` : ''}`;
            if (minutes) return `${minutes}m${remainder ? ` ${remainder}s` : ''}`;
            return `${remainder}s`;
        },
        speed(value) {
            if (value == null || !Number.isFinite(value)) return '—';
            let amount = Math.max(0, value), unit = 0;
            const units = ['B/s', 'KiB/s', 'MiB/s', 'GiB/s'];
            while (amount >= 1024 && unit < units.length - 1) { amount /= 1024; unit++; }
            return `${amount.toFixed(unit ? 1 : 0)} ${units[unit]}`;
        },
    };
})();
