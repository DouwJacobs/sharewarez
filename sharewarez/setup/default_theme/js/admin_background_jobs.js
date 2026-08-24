document.addEventListener('DOMContentLoaded', () => {
    const shell = document.querySelector('.jobs-admin-shell[data-live-refresh-url]');
    if (!shell) return;

    const refreshUrl = shell.dataset.liveRefreshUrl;
    let refreshPending = false;

    async function refreshJobs() {
        if (document.hidden || refreshPending) return;
        refreshPending = true;
        try {
            const requestUrl = new URL(refreshUrl, window.location.origin);
            shell.querySelectorAll('.job-card[data-job-id]').forEach(card => {
                requestUrl.searchParams.append('job_id', card.dataset.jobId);
            });
            const response = await fetch(requestUrl, {
                headers: { 'X-Requested-With': 'background-jobs-live-refresh' },
                credentials: 'same-origin',
                cache: 'no-store',
            });
            if (!response.ok) return;

            const data = await response.json();
            shell.querySelectorAll('[data-job-summary-status] strong').forEach(summary => {
                summary.textContent = '0';
            });
            for (const [jobStatus, count] of Object.entries(data.counts || {})) {
                const summary = shell.querySelector(`[data-job-summary-status="${CSS.escape(jobStatus)}"] strong`);
                if (summary) summary.textContent = count;
            }

            for (const job of data.jobs || []) {
                const card = shell.querySelector(`.job-card[data-job-id="${CSS.escape(job.id)}"]`);
                if (!card) continue;
                const previousStatus = card.dataset.jobStatus;
                card.dataset.jobStatus = job.status;
                card.classList.remove(`status-${previousStatus}`);
                card.classList.add(`status-${job.status}`);
                const state = card.querySelector('.job-state');
                if (state) state.textContent = job.status.charAt(0).toUpperCase() + job.status.slice(1);
                const progressFill = card.querySelector('.job-progress-fill');
                if (progressFill) progressFill.style.setProperty('--job-progress', `${job.progress}%`);
                const progressLabel = card.querySelector('.job-progress > small');
                if (progressLabel) progressLabel.textContent = `${job.progress}%`;
                const message = card.querySelector('.job-message');
                if (message && job.progress_message) message.innerHTML = `<strong>Progress:</strong> ${escapeHtml(job.progress_message)}`;
            }

            const status = shell.querySelector('.jobs-live-status');
            if (status) status.title = `Last updated ${new Date().toLocaleTimeString()}`;
        } catch (_error) {
            // Temporary connection failures are retried on the next interval.
        } finally {
            refreshPending = false;
        }
    }

    function escapeHtml(value) {
        const span = document.createElement('span');
        span.textContent = value;
        return span.innerHTML;
    }

    const timer = window.setInterval(refreshJobs, 8000);
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) refreshJobs();
    });
    window.addEventListener('pagehide', () => window.clearInterval(timer), { once: true });
});
