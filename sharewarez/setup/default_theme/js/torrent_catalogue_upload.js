/* Manual snapshots are saved separately so other settings drafts stay intact. */
document.addEventListener('DOMContentLoaded', () => {
    const file = document.getElementById('torrentCatalogueFile');
    if (!file) return;
    const upload = document.getElementById('uploadTorrentCatalogue');
    const remove = document.getElementById('removeTorrentCatalogue');
    const summary = document.getElementById('uploadedCatalogueSummary');
    const result = document.getElementById('torrentCatalogueUploadResult');
    let catalogue = JSON.parse(document.getElementById('uploadedCatalogue').textContent);
    let pending = false;
    function render() {
        remove.hidden = !catalogue;
        summary.textContent = catalogue
            ? `${catalogue.name} · ${catalogue.entry_count.toLocaleString()} ${catalogue.entry_count === 1 ? 'entry' : 'entries'} · ${catalogue.filename} · Uploaded ${new Date(catalogue.uploaded_at).toLocaleString()}`
            : 'No uploaded catalogue. Add a file here or use a public catalogue URL above.';
        upload.textContent = catalogue ? 'Replace uploaded catalogue' : 'Upload catalogue';
    }
    async function save(removing) {
        if (pending) return;
        const selected = file.files[0];
        if (!removing && (!selected || !selected.name.toLowerCase().endsWith('.json'))) {
            result.textContent = 'Choose a .json catalogue file.';
            file.focus();
            return;
        }
        if (!removing && selected.size > 20 * 1024 * 1024) {
            result.textContent = 'Catalogue exceeds 20 MiB.';
            return;
        }
        const revision = catalogue ? catalogue.sha256 : '';
        const body = removing ? JSON.stringify({revision}) : new FormData();
        if (!removing) { body.append('file', selected); body.append('revision', revision); }
        pending = true;
        upload.disabled = remove.disabled = file.disabled = true;
        result.textContent = removing ? 'Removing uploaded catalogue…' : 'Validating and saving catalogue…';
        try {
            const response = await fetch('/admin/torrent-catalogues/upload', {
                method: removing ? 'DELETE' : 'POST',
                headers: CSRFUtils.getHeaders(removing ? {'Content-Type': 'application/json'} : {}), body
            });
            const data = await response.json().catch(() => ({error: 'Unable to save the catalogue. Try again.'}));
            if (!response.ok) throw new Error(data.error || 'Unable to save the catalogue.');
            catalogue = data.catalogue;
            file.value = '';
            render();
            result.textContent = data.message;
        } catch (error) { result.textContent = error.message; }
        finally {
            pending = false;
            upload.disabled = remove.disabled = file.disabled = false;
            if (removing && !catalogue) upload.focus();
        }
    }
    upload.addEventListener('click', () => save(false));
    remove.addEventListener('click', () => save(true));
    render();
});
