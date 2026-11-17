(() => {
  const editor = document.querySelector('[data-torrent-editor]');
  const csrf = () => document.querySelector('input[name="csrf_token"]')?.value || document.querySelector('meta[name="csrf-token"]')?.content;
  if (editor) {
    editor.querySelector('[data-source-error]')?.focus();
    let counter = editor.querySelectorAll('.torrent-source-row').length;
    editor.querySelector('[data-add-source-row]').addEventListener('click', () => {
      const row = editor.querySelector('.torrent-source-row').cloneNode(true);
      counter++;
      row.querySelectorAll('input, textarea').forEach((input, i) => {
        const old = input.id;
        input.id = `new-source-${counter}-${i}`;
        row.querySelector(`label[for="${old}"]`).htmlFor = input.id;
        input.value = '';
      });
      editor.querySelector('[data-source-rows]').append(row);
      row.querySelector('input').focus();
    });
    editor.addEventListener('click', async event => {
      const removeRow = event.target.closest('[data-remove-source-row]');
      if (removeRow) {
        const row = removeRow.closest('.torrent-source-row');
        if (editor.querySelectorAll('.torrent-source-row').length > 1) row.remove();
        else row.querySelectorAll('input, textarea').forEach(input => { input.value = ''; });
        editor.querySelector('[data-add-source-row]').focus();
        return;
      }
      const button = event.target.closest('[data-source-rename], [data-source-remove], [data-source-replace]');
      if (!button) return;
      const row = button.closest('[data-source-id]');
      const removing = button.hasAttribute('data-source-remove');
      const deletingGame = row.querySelector('[data-final-source-action]')?.value === 'delete';
      if (removing && !window.confirm(deletingGame ? 'Delete this game and its final source from the library?' : 'Remove this source and keep the game in the library?')) return;
      button.disabled = true;
      try {
        const replacing = button.hasAttribute('data-source-replace');
        const file = replacing ? row.querySelector('[data-replace-file]').files[0] : null;
        let body = JSON.stringify({revision: Number(row.dataset.revision), label: row.querySelector('input').value, retain_catalog: true, delete_game: deletingGame});
        let headers = {'Content-Type': 'application/json', 'X-CSRFToken': csrf()};
        if (replacing) {
          body = new FormData();
          body.set('revision', row.dataset.revision);
          body.set('label', row.querySelector('input').value);
          body.set('magnet', row.querySelector('[data-replace-magnet]').value);
          body.set('public', row.querySelector('[data-replace-public]').checked ? '1' : '0');
          body.set('keep_separate', row.querySelector('[data-replace-variants]').checked ? '1' : '0');
          if (file) body.set('file', file);
          headers = {'X-CSRFToken': csrf()};
        }
        const response = await fetch(`/games/${editor.dataset.game}/torrent-sources/${row.dataset.sourceId}`, {
          method: removing ? 'DELETE' : 'PATCH',
          headers, body, signal: AbortSignal.timeout(45000)
        });
        if (response.status === 413) throw new Error('Torrent uploads must not exceed 10 MiB.');
        if (!response.headers.get('Content-Type')?.includes('application/json')) throw new Error('Could not update source. Sign in again if your session expired.');
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Could not update source.');
        if (data.deleted_game) { window.location.href = data.redirect_url; return; }
        if (removing) { row.remove(); editor.querySelector('[data-add-source-row]').focus(); }
        else {
          row.dataset.revision = data.revision;
          if (replacing) {
            const kind = file ? 'Torrent' : 'Magnet';
            row.querySelector('[data-source-kind-label]').textContent = `${kind} source label`;
            row.querySelector('[data-replace-magnet]').value = '';
            row.querySelector('[data-replace-file]').value = '';
            row.querySelector('[data-replace-public]').checked = false;
            row.querySelector('[data-replace-variants]').checked = false;
            row.querySelector('details').open = false;
          }
        }
        editor.querySelector('[data-source-status]').textContent = removing ? 'Source removed.' : replacing ? 'Source replaced.' : 'Label saved.';
      } catch (error) { editor.querySelector('[data-source-status]').textContent = error.message; }
      finally { button.disabled = false; }
    });
    const mode = document.getElementById('source_mode');
    const path = document.getElementById('full_disk_path');
    const update = () => {
      if (path) { path.disabled = mode.value === 'torrent'; path.required = mode.value === 'local'; }
      const detach = document.getElementById('detach_local');
      if (detach) {
        detach.disabled = mode.value !== 'torrent';
        if (detach.disabled) detach.checked = false;
      }
    };
    mode?.addEventListener('change', update);
    if (mode) update();
  }
  document.addEventListener('click', async event => {
    const button = event.target.closest('[data-magnet-action]');
    if (!button) return;
    button.disabled = true;
    const status = document.querySelector('[data-torrent-action-status]');
    try {
      const response = await fetch(button.dataset.url, {cache: 'no-store', signal: AbortSignal.timeout(30000)});
      if (!response.ok) throw new Error('This source is unavailable.');
      const data = await response.json();
      if (button.dataset.magnetAction === 'copy') {
        await navigator.clipboard.writeText(data.magnet);
        status.textContent = 'Magnet copied.';
      } else {
        window.location.href = data.magnet;
        status.textContent = 'Opening your torrent client. You can also copy the magnet.';
      }
    } catch (error) { status.textContent = error.message; }
    finally { button.disabled = false; }
  });
})();
