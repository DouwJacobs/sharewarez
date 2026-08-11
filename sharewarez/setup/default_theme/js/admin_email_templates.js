document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('emailTemplateForm');
    const subject = document.getElementById('emailTemplateSubject');
    const body = document.getElementById('emailTemplateBody');
    const previewButton = document.getElementById('previewEmailTemplate');
    const previewSubject = document.getElementById('emailPreviewSubject');
    const previewFrame = document.getElementById('emailTemplatePreviewFrame');
    const error = document.getElementById('emailTemplateError');
    if (!form || !subject || !body || !previewButton || !previewFrame) return;

    document.querySelectorAll('.email-variable-chip').forEach((chip) => {
        chip.addEventListener('click', () => {
            const target = document.activeElement === subject ? subject : body;
            const token = `{{ ${chip.dataset.variable} }}`;
            const start = target.selectionStart ?? target.value.length;
            const end = target.selectionEnd ?? start;
            target.setRangeText(token, start, end, 'end');
            target.focus();
        });
    });

    previewButton.addEventListener('click', async () => {
        error.hidden = true;
        previewButton.disabled = true;
        const templateKey = form.elements.template_key.value;
        const data = new FormData();
        data.append('subject', subject.value);
        data.append('html', body.value);
        try {
            const response = await fetch(`/admin/email-templates/${encodeURIComponent(templateKey)}/preview`, {
                method: 'POST',
                headers: {'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content},
                body: data,
            });
            const result = await response.json();
            if (!response.ok || !result.success) throw new Error(result.error || 'Preview could not be rendered.');
            previewSubject.textContent = result.subject;
            previewFrame.srcdoc = result.html;
        } catch (previewError) {
            error.textContent = previewError.message;
            error.hidden = false;
        } finally {
            previewButton.disabled = false;
        }
    });
});
