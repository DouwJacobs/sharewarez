/* Derive all supported integration destinations from the actual tab controls. */
document.addEventListener('DOMContentLoaded', () => {
    const buttons = Array.from(document.querySelectorAll('#integrationTabs button[data-bs-toggle="tab"]'));
    const destinations = new Map(buttons.map(button => [button.getAttribute('data-bs-target'), button]));
    const aliases = {'#smtp':'#email', '#metadata':'#igdb'};
    function navigate() {
        const hash = aliases[window.location.hash] || window.location.hash;
        const flash = document.querySelector('.integrations-page')?.dataset.initialIntegrationTab;
        const target = destinations.has(hash) ? hash : destinations.has(flash) ? flash : buttons[0]?.getAttribute('data-bs-target');
        if (!target) return;
        if (window.location.hash !== target) history.replaceState(null, '', target);
        bootstrap.Tab.getOrCreateInstance(destinations.get(target)).show();
    }
    buttons.forEach(button => button.addEventListener('shown.bs.tab', event => {
        const hash = event.target.getAttribute('data-bs-target');
        if (window.location.hash !== hash) history.pushState(null, '', hash);
    }));
    window.addEventListener('hashchange', navigate);
    window.addEventListener('popstate', navigate);
    navigate();
});