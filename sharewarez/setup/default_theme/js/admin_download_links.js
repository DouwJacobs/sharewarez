const rowCheckboxes = () => Array.from(document.querySelectorAll('.download-row-select'));
const updateBulkSelection = () => {
    const selected = rowCheckboxes().filter(box => box.checked).length;
    const count = document.getElementById('bulkSelectedCount');
    if (count) count.textContent = selected;
    document.querySelectorAll('[data-bulk-action]').forEach(button => { button.disabled = selected === 0; });
};
function bindDeliveryLinks() {
    document.getElementById('selectAllDownloads')?.addEventListener('change', event => {
        rowCheckboxes().forEach(box => { box.checked = event.target.checked; });
        updateBulkSelection();
    });
    rowCheckboxes().forEach(box => box.addEventListener('change', updateBulkSelection));
    document.querySelectorAll('[data-bulk-action]').forEach(button => button.addEventListener('click', async () => {
        const ids = rowCheckboxes().filter(box => box.checked).map(box => Number(box.value));
        if (!ids.length) { $.notify('Select at least one request.', 'warning'); return; }
        const action = button.dataset.bulkAction;
        if (action === 'delete' && !window.confirm(`Delete ${ids.length} selected request(s)?`)) return;
        button.disabled = true;
        try {
            const response = await fetch('/api/downloads/bulk', {
                method: 'POST', headers: CSRFUtils.getHeaders({'Content-Type': 'application/json'}),
                body: JSON.stringify({action, ids})
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.message || 'Bulk action failed');
            $.notify(data.message, 'success');
            window.location.reload();
        } catch (error) { $.notify(error.message, 'error'); button.disabled = false; }
    }));

    document.querySelectorAll('.download-priority-select').forEach(select => {
        select.addEventListener('change', async () => {
            const previous = select.dataset.savedValue ?? '0';
            select.disabled = true;
            try {
                const response = await fetch(`/admin/download-priority/${select.dataset.requestId}`, {
                    method: 'POST',
                    headers: CSRFUtils.getHeaders({'Content-Type': 'application/json'}),
                    body: JSON.stringify({priority: Number(select.value)})
                });
                const data = await response.json();
                if (!response.ok) throw new Error(data.message || 'Could not update priority');
                select.dataset.savedValue = select.value;
                $.notify(data.message, 'success');
            } catch (error) {
                select.value = previous;
                $.notify(error.message, 'error');
            } finally {
                select.disabled = false;
            }
        });
        select.dataset.savedValue = select.value;
    });

}
bindDeliveryLinks();
document.addEventListener('delivery-updated', bindDeliveryLinks);


let currentDeleteId = null;

function showDeleteModal(requestId) {
    currentDeleteId = requestId;
    const modal = new bootstrap.Modal(document.getElementById('deleteConfirmModal'));
    modal.show();
}

function confirmDelete() {
    if (currentDeleteId) {
        fetch(`/api/delete_download/${currentDeleteId}`, {
            method: 'DELETE',
            headers: CSRFUtils.getHeaders({
                'Content-Type': 'application/json'
            })
        })
        .then(response => response.json())
        .then(data => {
            const modal = bootstrap.Modal.getInstance(document.getElementById('deleteConfirmModal'));
            modal.hide();

            if (data.status === 'success') {
                $.notify(data.message, "success");
                window.location.reload();
            } else if (data.status === 'warning') {
                $.notify(data.message, "warn");
            } else {
                $.notify(data.message, "error");
            }
        })
        .catch(error => {
            console.error('Error:', error);
            $.notify("An error occurred while deleting the download", "error");
        });
    }
}
