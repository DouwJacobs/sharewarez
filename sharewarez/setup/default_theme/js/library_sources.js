// Delegate to document so freshly paginated cards behave like initial cards.
document.addEventListener('click', async function(event) {
    const link = event.target.closest('[data-card-magnet-url]');
    if (!link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    event.stopPropagation();
    if (link.getAttribute('aria-busy') === 'true') return;
    link.setAttribute('aria-busy', 'true');
    try {
        const response = await fetch(link.dataset.cardMagnetUrl, {method: 'POST', headers: CSRFUtils.getHeaders(), cache: 'no-store', signal: AbortSignal.timeout(30000)});
        if (!response.ok) throw new Error('Source unavailable');
        const data = await response.json();
        if (typeof data.magnet !== 'string' || !data.magnet.startsWith('magnet:?')) throw new Error('Invalid source');
        const previousFeedback = link.closest('.game-card-container').querySelector('.library-game-copy').querySelector('[data-card-source-feedback]');
        if (previousFeedback) previousFeedback.textContent = '';
        window.location.href = data.magnet;
    } catch (error) {
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
        feedback.textContent = error.name === 'TimeoutError' ? 'Source lookup timed out. Please try again.' : 'Source unavailable. Open the game to review its sources.';
    } finally {
        link.removeAttribute('aria-busy');
    }
});
