document.addEventListener('DOMContentLoaded', () => {
    const preview = document.getElementById('themeBuilderPreview');
    const form = document.getElementById('themeBuilderForm');
    if (!preview || !form) return;

    const defaults = {
        accent: '#557cf4', accent_soft: '#9ab1ff', background: '#0a0b14',
        sidebar: '#12131f', card: '#12121c', panel: '#181925',
        text_primary: '#f5f7ff', text_secondary: '#c5ccdc'
    };
    const variableNames = {
        accent: '--preview-accent', accent_soft: '--preview-soft', background: '--preview-bg',
        sidebar: '--preview-sidebar', card: '--preview-card', panel: '--preview-panel',
        text_primary: '--preview-text-primary', text_secondary: '--preview-text-secondary'
    };

    function updatePreview() {
        Object.entries(variableNames).forEach(([field, variable]) => {
            const input = form.elements[field];
            preview.style.setProperty(variable, input.value);
            const value = form.querySelector(`[data-color-value="${field}"]`);
            if (value) value.textContent = input.value.toUpperCase();
        });
        const name = form.elements.name.value.trim();
        preview.querySelector('[data-preview-name]').textContent = name || 'Your theme';
    }

    form.querySelectorAll('input[type="color"], #name').forEach(input => input.addEventListener('input', updatePreview));
    document.getElementById('resetThemePreview')?.addEventListener('click', () => {
        Object.entries(defaults).forEach(([field, value]) => { form.elements[field].value = value; });
        updatePreview();
    });
    updatePreview();
});
