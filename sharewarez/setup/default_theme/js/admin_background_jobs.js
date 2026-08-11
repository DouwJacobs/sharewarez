document.addEventListener('DOMContentLoaded', () => {
    const shell = document.querySelector('.jobs-admin-shell[data-live-refresh-url]');
    if (!shell) return;

    const refreshUrl = shell.dataset.liveRefreshUrl;
    let refreshPending = false;

    async function refreshJobs() {
        if (document.hidden || refreshPending) return;
        refreshPending = true;
        try {
            const response = await fetch(refreshUrl, {
                headers: { 'X-Requested-With': 'background-jobs-live-refresh' },
                credentials: 'same-origin',
                cache: 'no-store',
            });
            if (!response.ok) return;

            const nextDocument = new DOMParser().parseFromString(await response.text(), 'text/html');
            const openJobIds = new Set(
                [...shell.querySelectorAll('.job-card[open]')].map((card) => card.dataset.jobId),
            );

            for (const selector of ['.job-summary', '.job-list']) {
                const current = shell.querySelector(selector);
                const next = nextDocument.querySelector(selector);
                if (current && next) current.replaceWith(next);
            }

            for (const jobId of openJobIds) {
                const card = shell.querySelector(`.job-card[data-job-id="${CSS.escape(jobId)}"]`);
                if (card) card.open = true;
            }

            const status = shell.querySelector('.jobs-live-status');
            if (status) status.title = `Last updated ${new Date().toLocaleTimeString()}`;
        } catch (_error) {
            // Temporary connection failures are retried on the next interval.
        } finally {
            refreshPending = false;
        }
    }

    const timer = window.setInterval(refreshJobs, 3000);
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) refreshJobs();
    });
    window.addEventListener('pagehide', () => window.clearInterval(timer), { once: true });
});
