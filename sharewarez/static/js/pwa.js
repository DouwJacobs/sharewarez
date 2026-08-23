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

    const pushButton = document.querySelector('[data-push-toggle]');
    if (!pushButton || !('PushManager' in window)) return;
    pushButton.hidden = false;

    const decodeKey = value => {
        const padded = `${value}${'='.repeat((4 - value.length % 4) % 4)}`;
        return Uint8Array.from(atob(padded.replace(/-/g, '+').replace(/_/g, '/')), char => char.charCodeAt(0));
    };
    const csrf = () => document.querySelector('meta[name="csrf-token"]')?.content || '';

    navigator.serviceWorker.ready.then(async registration => {
        const current = await registration.pushManager.getSubscription();
        pushButton.textContent = current ? 'Disable browser alerts' : 'Enable browser alerts';
        pushButton.addEventListener('click', async () => {
            pushButton.disabled = true;
            try {
                let subscription = await registration.pushManager.getSubscription();
                if (subscription) {
                    await fetch('/api/push/subscriptions', {
                        method: 'DELETE',
                        headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf()},
                        body: JSON.stringify({endpoint: subscription.endpoint})
                    });
                    await subscription.unsubscribe();
                    pushButton.textContent = 'Enable browser alerts';
                    return;
                }
                if (await Notification.requestPermission() !== 'granted') return;
                const keyResponse = await fetch('/api/push/public-key');
                const {publicKey} = await keyResponse.json();
                subscription = await registration.pushManager.subscribe({
                    userVisibleOnly: true,
                    applicationServerKey: decodeKey(publicKey)
                });
                await fetch('/api/push/subscriptions', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf()},
                    body: JSON.stringify(subscription)
                });
                pushButton.textContent = 'Disable browser alerts';
            } finally {
                pushButton.disabled = false;
            }
        });
    });
})();
