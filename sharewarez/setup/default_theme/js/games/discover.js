document.addEventListener('DOMContentLoaded', () => {
    const carousel = document.querySelector('[data-featured-carousel]');
    if (!carousel) return;
    const slides = [...carousel.querySelectorAll('[data-featured-slide]')];
    const dots = [...carousel.querySelectorAll('[data-featured-dot]')];
    if (slides.length < 2) return;

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let activeIndex = 0;
    let timer;
    let paused = false;
    let touchStartX = null;
    let touchStartY = null;

    const show = index => {
        activeIndex = (index + slides.length) % slides.length;
        slides.forEach((slide, slideIndex) => {
            const active = slideIndex === activeIndex;
            slide.classList.toggle('is-active', active);
            slide.setAttribute('aria-hidden', String(!active));
        });
        dots.forEach((dot, dotIndex) => {
            const active = dotIndex === activeIndex;
            dot.classList.toggle('is-active', active);
            dot.setAttribute('aria-selected', String(active));
        });
    };
    const stop = () => window.clearInterval(timer);
    const start = () => {
        stop();
        if (!reduceMotion && !paused && !document.hidden) timer = window.setInterval(() => show(activeIndex + 1), 7000);
    };

    carousel.querySelector('[data-featured-previous]')?.addEventListener('click', () => { show(activeIndex - 1); start(); });
    carousel.querySelector('[data-featured-next]')?.addEventListener('click', () => { show(activeIndex + 1); start(); });
    dots.forEach(dot => dot.addEventListener('click', () => { show(Number(dot.dataset.featuredDot)); start(); }));
    carousel.addEventListener('mouseenter', () => { paused = true; stop(); });
    carousel.addEventListener('mouseleave', () => { paused = false; start(); });
    carousel.addEventListener('focusin', () => { paused = true; stop(); });
    carousel.addEventListener('focusout', event => {
        if (!carousel.contains(event.relatedTarget)) { paused = false; start(); }
    });
    carousel.addEventListener('touchstart', event => {
        const touch = event.changedTouches[0];
        touchStartX = touch.clientX;
        touchStartY = touch.clientY;
        paused = true;
        stop();
    }, { passive: true });
    carousel.addEventListener('touchend', event => {
        if (touchStartX === null || touchStartY === null) return;
        const touch = event.changedTouches[0];
        const deltaX = touch.clientX - touchStartX;
        const deltaY = touch.clientY - touchStartY;
        touchStartX = null;
        touchStartY = null;

        if (Math.abs(deltaX) >= 48 && Math.abs(deltaX) > Math.abs(deltaY) * 1.25) {
            show(activeIndex + (deltaX < 0 ? 1 : -1));
        }
        paused = false;
        start();
    }, { passive: true });
    carousel.addEventListener('touchcancel', () => {
        touchStartX = null;
        touchStartY = null;
        paused = false;
        start();
    }, { passive: true });
    document.addEventListener('visibilitychange', start);
    start();
});

document.addEventListener('DOMContentLoaded', () => {
    const panel = document.querySelector('[data-discover-customizer]');
    if (!panel) return;
    const list = panel.querySelector('.discover-customizer-list');
    list.addEventListener('click', event => {
        const button = event.target.closest('[data-move]');
        if (!button) return;
        const row = button.closest('[data-discover-section]');
        const sibling = button.dataset.move === 'up' ? row.previousElementSibling : row.nextElementSibling;
        if (!sibling) return;
        if (button.dataset.move === 'up') list.insertBefore(row, sibling);
        else list.insertBefore(sibling, row);
    });

    panel.querySelector('[data-discover-save]')?.addEventListener('click', async event => {
        const button = event.currentTarget;
        const rows = [...list.querySelectorAll('[data-discover-section]')];
        button.disabled = true;
        try {
            const response = await fetch('/api/preferences/discover', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': CSRFUtils.getToken(),
                },
                body: JSON.stringify({
                    order: rows.map(row => row.dataset.discoverSection),
                    hidden: rows.filter(row => !row.querySelector('input').checked).map(row => row.dataset.discoverSection),
                }),
            });
            if (!response.ok) throw new Error((await response.json()).error || 'Unable to save layout.');
            window.location.reload();
        } catch (error) {
            button.disabled = false;
            button.textContent = error.message;
        }
    });
});
