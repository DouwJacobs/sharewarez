document.addEventListener('DOMContentLoaded', () => {
    let delay = 3000;
    const refresh = async () => {
        if (document.hidden) { window.setTimeout(refresh, delay); return; }
        try {
            const response = await fetch('/admin/download-cache/status', {cache: 'no-store'});
            if (!response.ok) throw new Error('Cache status unavailable');
            const payload = await response.json();
            const data = payload.data;
            const formatter = new Intl.NumberFormat(undefined, {style: 'unit', unit: 'megabyte', maximumFractionDigits: 1});
            const asMb = value => formatter.format((value || 0) / 1000000);
            document.getElementById('cacheUsed').textContent = asMb(data.used_bytes);
            document.getElementById('cacheFree').textContent = asMb(data.free_bytes);
            document.getElementById('cacheReady').textContent = `${data.counts.ready} archive${data.counts.ready === 1 ? '' : 's'}`;
            document.getElementById('cacheBuilding').textContent = data.counts.queued + data.counts.building;
            document.getElementById('cacheFailed').textContent = data.counts.failed;
            delay = 3000;
        } catch (_error) { delay = Math.min(delay * 2, 30000); }
        window.setTimeout(refresh, delay);
    };
    window.setTimeout(refresh, delay);
});
