document.addEventListener('DOMContentLoaded', function() {
    $(document).on('submit', '#preferencesForm', function(event) {
        event.preventDefault();
        
        const formData = new FormData(this);
        const csrfToken = CSRFUtils.getToken();
        
        fetch(this.action, {
            method: 'POST',
            body: formData,
            headers: CSRFUtils.getHeaders()
        })
        .then(async response => {
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                const validationMessage = Object.values(data.errors || {}).flat()[0];
                throw new Error(validationMessage || data.message || 'Could not save preferences');
            }
            return data;
        })
        .then(data => {
            if (data.success) {
                // Close modal
                const modal = bootstrap.Modal.getInstance(document.getElementById('preferencesModal'));
                if (modal) {
                    modal.hide();
                }
                
                // Show success message
                $.notify(data.message, "success");
                
                // Reload page after short delay to apply new preferences
                setTimeout(() => window.location.reload(), 1000);
            } else {
                // Show error messages
                Object.values(data.errors || {}).forEach(error => {
                    $.notify(error[0], "error");
                });
            }
        })
        .catch(error => {
            console.error('Error:', error);
            $.notify(error.message || "An error occurred while saving preferences", "error");
        });
    });
});
