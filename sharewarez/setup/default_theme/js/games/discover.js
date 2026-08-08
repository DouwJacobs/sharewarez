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
    document.addEventListener('visibilitychange', start);
    start();
});
