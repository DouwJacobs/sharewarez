/**
 * Keep dialogs in the document's top layer.
 *
 * Page content uses transforms for entry animation and layout. A transformed
 * ancestor creates a stacking context, while Bootstrap appends its backdrop
 * directly to <body>. Moving dialogs alongside that backdrop prevents the
 * backdrop from appearing above the dialog and intercepting all interaction.
 */
(function () {
    function moveModalToBody(modal) {
        if (modal instanceof HTMLElement && modal.parentElement !== document.body) {
            document.body.appendChild(modal);
        }
    }

    function moveExistingModals() {
        document.querySelectorAll('.modal').forEach(moveModalToBody);
    }

    document.addEventListener('DOMContentLoaded', moveExistingModals);

    // Bootstrap emits this before it creates/shows the backdrop. Capture the
    // event so dynamically inserted dialogs are fixed before layering begins.
    document.addEventListener('show.bs.modal', function (event) {
        moveModalToBody(event.target);
    }, true);
})();
