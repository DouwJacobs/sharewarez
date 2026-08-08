(() => {
    const installButtons = [...document.querySelectorAll('[data-pwa-install]')];
    let installPrompt = null;

    const setInstallVisible = visible => {
        installButtons.forEach(button => { button.hidden = !visible; });
    };

    const isInstalled = window.matchMedia('(display-mode: standalone)').matches
        || window.navigator.standalone === true;
    setInstallVisible(false);

    window.addEventListener('beforeinstallprompt', event => {
        event.preventDefault();
        installPrompt = event;
        if (!isInstalled) setInstallVisible(true);
    });

    installButtons.forEach(button => {
        button.addEventListener('click', async () => {
            if (!installPrompt) return;
            setInstallVisible(false);
            await installPrompt.prompt();
            await installPrompt.userChoice;
            installPrompt = null;
        });
    });

    window.addEventListener('appinstalled', () => {
        installPrompt = null;
        setInstallVisible(false);
    });

    if (!('serviceWorker' in navigator) || !window.isSecureContext) return;

    const showUpdateNotice = () => {
        if (document.querySelector('.pwa-update-notice')) return;
        const notice = document.createElement('div');
        notice.className = 'pwa-update-notice';
        notice.setAttribute('role', 'status');
        notice.innerHTML = '<span><i class="fas fa-arrow-rotate-right" aria-hidden="true"></i> App update ready</span><button type="button">Reload</button>';
        notice.querySelector('button').addEventListener('click', () => window.location.reload());
        document.body.appendChild(notice);
    };

    window.addEventListener('load', async () => {
        const hadController = Boolean(navigator.serviceWorker.controller);
        try {
            await navigator.serviceWorker.register('/service-worker.js', { scope: '/' });
            navigator.serviceWorker.addEventListener('controllerchange', () => {
                if (hadController) showUpdateNotice();
            });
        } catch (error) {
            console.warn('PWA service worker registration failed.', error);
        }
    });
})();
