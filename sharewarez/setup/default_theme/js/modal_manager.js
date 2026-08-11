/**
 * Keep dialogs in the document's top layer.
 *
 * Page content uses transforms for entry animation and layout. A transformed
 * ancestor creates a stacking context, while Bootstrap appends its backdrop
 * directly to <body>. Moving dialogs alongside that backdrop prevents the
 * backdrop from appearing above the dialog and intercepting all interaction.
 */
(function () {
    const managedSelector = '[data-focus-managed-dialog]';
    const focusableSelector = [
        'a[href]', 'button:not([disabled])', 'input:not([disabled])',
        'select:not([disabled])', 'textarea:not([disabled])',
        '[tabindex]:not([tabindex="-1"])'
    ].join(',');
    const returnFocus = new WeakMap();
    const bootstrapReturnFocus = new WeakMap();

    function isOpen(dialog) {
        return !dialog.hidden && getComputedStyle(dialog).display !== 'none' &&
            getComputedStyle(dialog).visibility !== 'hidden';
    }

    function focusableElements(dialog) {
        return [...dialog.querySelectorAll(focusableSelector)].filter(element =>
            element.getClientRects().length > 0 && element.getAttribute('aria-hidden') !== 'true'
        );
    }

    function activateDialog(dialog) {
        if (dialog.dataset.focusManagedOpen === 'true') return;
        dialog.dataset.focusManagedOpen = 'true';
        returnFocus.set(dialog, document.activeElement);
        dialog.setAttribute('aria-hidden', 'false');
        requestAnimationFrame(() => {
            const target = dialog.querySelector('[autofocus], [data-dialog-initial-focus]') ||
                focusableElements(dialog)[0] || dialog;
            if (!dialog.hasAttribute('tabindex')) dialog.tabIndex = -1;
            target.focus({preventScroll: true});
        });
    }

    function deactivateDialog(dialog) {
        if (dialog.dataset.focusManagedOpen !== 'true') return;
        delete dialog.dataset.focusManagedOpen;
        dialog.setAttribute('aria-hidden', 'true');
        const target = returnFocus.get(dialog);
        returnFocus.delete(dialog);
        if (target instanceof HTMLElement && target.isConnected) {
            requestAnimationFrame(() => target.focus({preventScroll: true}));
        }
    }

    function syncDialog(dialog) {
        if (isOpen(dialog)) activateDialog(dialog);
        else deactivateDialog(dialog);
    }

    function initializeManagedDialogs() {
        document.querySelectorAll(managedSelector).forEach(dialog => {
            syncDialog(dialog);
            new MutationObserver(() => syncDialog(dialog)).observe(dialog, {
                attributes: true,
                attributeFilter: ['class', 'style', 'hidden']
            });
        });
    }

    function moveModalToBody(modal) {
        if (modal instanceof HTMLElement && modal.parentElement !== document.body) {
            document.body.appendChild(modal);
        }
    }

    function moveExistingModals() {
        document.querySelectorAll(`.modal, ${managedSelector}`).forEach(moveModalToBody);
    }

    document.addEventListener('DOMContentLoaded', function () {
        moveExistingModals();
        initializeManagedDialogs();
    });

    document.addEventListener('keydown', function (event) {
        const dialogs = [...document.querySelectorAll(managedSelector)].filter(isOpen);
        const dialog = dialogs.at(-1);
        if (!dialog) return;

        if (event.key === 'Escape') {
            const close = dialog.querySelector('[data-dialog-close]');
            if (close) {
                event.preventDefault();
                close.click();
            }
            return;
        }

        if (event.key !== 'Tab') return;
        const elements = focusableElements(dialog);
        if (!elements.length) {
            event.preventDefault();
            dialog.focus();
            return;
        }
        const first = elements[0];
        const last = elements.at(-1);
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    });

    // Bootstrap emits this before it creates/shows the backdrop. Capture the
    // event so dynamically inserted dialogs are fixed before layering begins.
    document.addEventListener('show.bs.modal', function (event) {
        bootstrapReturnFocus.set(event.target, document.activeElement);
        moveModalToBody(event.target);
    }, true);

    document.addEventListener('hidden.bs.modal', function (event) {
        const target = bootstrapReturnFocus.get(event.target);
        bootstrapReturnFocus.delete(event.target);
        if (target instanceof HTMLElement && target.isConnected) {
            requestAnimationFrame(() => target.focus({preventScroll: true}));
        }
    }, true);
})();
