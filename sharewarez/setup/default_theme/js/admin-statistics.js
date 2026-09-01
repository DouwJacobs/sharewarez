document.addEventListener('DOMContentLoaded', () => {
    const status = document.getElementById('statisticsStatus');
    const grid = document.querySelector('.statistics-grid');
    const styles = getComputedStyle(document.documentElement);
    const accentRgb = styles.getPropertyValue('--theme-accent-rgb').trim() || '117, 84, 214';
    const mutedRgb = styles.getPropertyValue('--theme-accent-soft-rgb').trim() || accentRgb;
    const accent = `rgba(${accentRgb}, .72)`;
    const accentLine = `rgb(${accentRgb})`;
    const secondary = `rgba(${mutedRgb}, .56)`;

    const setText = (id, value) => { const node = document.getElementById(id); if (node) node.textContent = value; };
    const total = values => (values || []).reduce((sum, value) => sum + Number(value || 0), 0);
    const formatBytes = value => {
        let size = Number(value || 0);
        if (!size) return '0 B';
        const units = ['B', 'KB', 'MB', 'GB', 'TB', 'PB'];
        let unit = 0;
        while (size >= 1024 && unit < units.length - 1) { size /= 1024; unit += 1; }
        return `${size.toFixed(unit && size < 100 ? 2 : 0)} ${units[unit]}`;
    };
    const showEmpty = canvasId => {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;
        canvas.hidden = true;
        const empty = canvas.parentElement.querySelector('.chart-empty');
        if (empty) empty.hidden = false;
    };
    const renderChart = (canvasId, type, series, options = {}) => {
        if (!series?.data?.length) { showEmpty(canvasId); return; }
        createChart(canvasId, type, { labels: series.labels, datasets: [{ label: options.label, data: series.data, backgroundColor: options.fill || accent, borderColor: options.line || accentLine, borderWidth: 1, tension: .25, fill: type === 'line' }] }, {
            responsive: true,
            maintainAspectRatio: false,
            indexAxis: options.horizontal ? 'y' : 'x',
            plugins: { legend: { display: false }, title: { display: false } },
            scales: {
                x: { beginAtZero: options.horizontal, ticks: { precision: 0 } },
                y: { beginAtZero: !options.horizontal, ticks: { precision: 0 } },
            },
        });
    };

    fetch('/admin/statistics/data', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
        .then(response => { if (!response.ok) throw new Error('Unable to load statistics'); return response.json(); })
        .then(data => {
            setText('statTotalDownloads', total(data.downloads_per_user.data).toLocaleString());
            setText('statActiveUsers', data.downloads_per_user.labels.length.toLocaleString());
            setText('statCompletedBytes', formatBytes(data.transfer_summary?.completed_bytes));
            setText('statTopGame', data.top_games.labels[0] || 'None yet');
            renderChart('downloadTrendsChart', 'line', data.download_trends, { label: 'Downloads', fill: `rgba(${accentRgb}, .16)` });
            renderChart('topGamesChart', 'bar', data.top_games, { label: 'Downloads', horizontal: true });
            renderChart('topDownloadersChart', 'bar', data.top_downloaders, { label: 'Downloads', horizontal: true, fill: secondary });
            renderChart('topCollectorsChart', 'bar', data.top_collectors, { label: 'Favorites', horizontal: true });
            renderChart('inviteTokensChart', 'bar', data.users_with_invites, { label: 'Invites', horizontal: true, fill: secondary });
            status.textContent = 'Updated just now';
        })
        .catch(error => { console.error('Error loading statistics:', error); status.textContent = 'Statistics could not be loaded. Try refreshing the page.'; })
        .finally(() => grid?.setAttribute('aria-busy', 'false'));
});
