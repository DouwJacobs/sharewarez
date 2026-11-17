// Delegate to document so freshly paginated cards behave like initial cards.
document.addEventListener('click', async function(event) {
    const link = event.target.closest('[data-card-magnet-url]');
    if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    event.stopPropagation();
    if (link.getAttribute('aria-busy') === 'true') return;
    link.setAttribute('aria-busy', 'true');
    const copyArea = link.closest('.game-card-container').querySelector('.library-game-copy');
    let feedback = copyArea.querySelector('[data-card-source-feedback]');
    if (!feedback) {
        feedback = document.createElement('div');
        feedback.dataset.cardSourceFeedback = 'true';
        feedback.className = 'library-source-feedback';
        feedback.setAttribute('role', 'status');
        feedback.setAttribute('aria-live', 'polite');
        copyArea.append(feedback);
    }
    feedback.textContent = 'Opening your torrent client…';
    try {
        const response = await fetch(link.dataset.cardMagnetUrl, {cache: 'no-store', signal: AbortSignal.timeout(30000)});
        if (!response.ok) throw new Error('Source unavailable');
        const data = await response.json();
        if (typeof data.magnet !== 'string' || !data.magnet.startsWith('magnet:?')) throw new Error('Invalid source');
        const message = document.createElement('span');
        message.textContent = 'Client did not open?';
        const copy = document.createElement('button');
        copy.type = 'button';
        copy.className = 'btn btn-secondary library-source-copy';
        copy.title = 'Copy magnet';
        copy.setAttribute('aria-label', 'Copy magnet');
        const icon = document.createElement('i');
        icon.className = 'fas fa-copy';
        icon.setAttribute('aria-hidden', 'true');
        copy.append(icon);
        copy.addEventListener('click', async () => {
            try {
                await navigator.clipboard.writeText(data.magnet);
                message.textContent = 'Magnet copied.';
            } catch (error) {
                message.textContent = 'Clipboard unavailable. Open the game to copy the link.';
            }
        });
        feedback.replaceChildren(message, copy);
        window.location.href = data.magnet;
    } catch (error) {
        feedback.textContent = error.name === 'TimeoutError' ? 'Source lookup timed out. Please try again.' : 'Source unavailable. Open the game to review its sources.';
    } finally {
        link.removeAttribute('aria-busy');
    }
});
