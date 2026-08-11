function debounce(func, wait, immediate) {
    var timeout;
    return function() {
        var context = this, args = arguments;
        var later = function() {
            timeout = null;
            if (!immediate) func.apply(context, args);
        };
        var callNow = immediate && !timeout;
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
        if (callNow) func.apply(context, args);
    };
}

const slideshowIntervals = {};
const hoverPreviewMedia = window.matchMedia('(hover: hover) and (pointer: fine)');

function escapeHtml(value) {
    const element = document.createElement('div');
    element.textContent = value;
    return element.innerHTML;
}

function startSlideshowForGameUuid(gameUuid) {
    if (slideshowIntervals[gameUuid]) {
        clearTimeout(slideshowIntervals[gameUuid]);
    }

    let slideIndex = 0;
    const slides = document.querySelectorAll(`#details-${gameUuid} .screenshot-slide`);
    if (slides.length === 0) return;

    const showSlides = () => {
        slides.forEach(slide => slide.style.display = "none");
        slideIndex++;
        if (slideIndex > slides.length) slideIndex = 1;
        slides[slideIndex - 1].style.display = "block";
        slideshowIntervals[gameUuid] = setTimeout(showSlides, 2000); 
    };
    showSlides();
}

function clearSlideshowForGameUuid(gameUuid) {
    if (slideshowIntervals[gameUuid]) {
        clearTimeout(slideshowIntervals[gameUuid]);
        delete slideshowIntervals[gameUuid]; 
    }
}

const showDetailsDebounced = debounce(function(element, gameUuid, rowid) {
	
	var isHovered = $(element).is(":hover");
    
	if (rowid) {
		var detailsDiv = document.getElementById(`details-${gameUuid}-${rowid}`);
	} else {
		var detailsDiv = document.getElementById(`details-${gameUuid}`);
	}
	
    if (!detailsDiv) {
        return;
    }
	
	if (isHovered) {

    // prevent flickering and overlapping animations
    detailsDiv.innerHTML = '';
    clearSlideshowForGameUuid(gameUuid);

    fetch(`/api/game_screenshots/${gameUuid}`)
        .then(response => {
            if (response.ok) {
                return response.json();
            } else {
                throw new Error('Network response was not ok.');
            }
        })
        .then(screenshots => {
            let detailsHtml = '<div class="library-hover-preview-media"><div class="slides-wrapper">';
            screenshots.forEach((url, index) => {
                detailsHtml += `<div class="screenshot-slide" style="display: ${index === 0 ? 'block' : 'none'};"><img src="${escapeHtml(url)}" class="screenshot" alt=""></div>`;
            });
            if (!screenshots.length) {
                detailsHtml += '<div class="library-hover-preview-placeholder"><i class="fas fa-image" aria-hidden="true"></i></div>';
            }
            detailsHtml += '</div><span class="library-hover-preview-kicker">Quick look</span></div>';

            const tags = (element.dataset.tags || '').split(', ').filter(Boolean);
            const genres = (element.dataset.genres || '').split(', ').filter(Boolean);
            const tagsHtml = tags.length
                ? `<div class="game-card-hover-tags"><span class="game-card-hover-label">Tags</span><div class="library-hover-preview-chips">${tags.slice(0, 3).map(tag => `<span class="chip">${escapeHtml(tag)}</span>`).join('')}</div></div>`
                : '';
            const genresHtml = genres.length
                ? `<div class="library-hover-preview-chips">${genres.slice(0, 3).map(genre => `<span class="chip">${escapeHtml(genre)}</span>`).join('')}</div>`
                : '<span class="library-hover-preview-muted">No genres available</span>';

            detailsHtml += `<div class="game-info-box">
                                <div class="library-hover-preview-heading">
                                    <h3 class="game-name">${escapeHtml(element.dataset.name || 'Untitled game')}</h3>
                                    <span class="game-size"><i class="fas fa-hard-drive" aria-hidden="true"></i>${escapeHtml(element.dataset.size || 'Unknown size')}</span>
                                </div>
                                ${genresHtml}
                                ${tagsHtml}
                            </div>`;

            detailsDiv.innerHTML = detailsHtml;

            startSlideshowForGameUuid(gameUuid);
            detailsDiv.classList.remove('hidden');
            detailsDiv.setAttribute('aria-hidden', 'false');
            element.closest('.game-card-container')?.classList.add('preview-open');
        })
        .catch(error => {
            console.error('Fetch error:', error);
        });
        adjustDetailsSizeForGameUuid(gameUuid); 
	}
}, 300); // 300 ms

function showDetails(element, gameUuid, rowid) {
	if (!hoverPreviewMedia.matches) return;
	
	if (rowid) {
		var detailsDiv = document.getElementById(`details-${gameUuid}-${rowid}`);
	} else {
		var detailsDiv = document.getElementById(`details-${gameUuid}`);
	}
	
    if (!detailsDiv) {
        return;
    }

    showDetailsDebounced(element, gameUuid, rowid);

    // Calculate the space needed for the popup
    const popupWidth = 360;
    const viewportWidth = window.innerWidth;
    const gameCardRect = element.getBoundingClientRect();
    const spaceOnRight = viewportWidth - gameCardRect.right;

    // Check if there's enough space on the right, if not, adjust to show on the left
    if (spaceOnRight < popupWidth + 28) {
        detailsDiv.style.left = 'auto';
        detailsDiv.style.right = 'calc(100% + 14px)';
    } else {
        detailsDiv.style.right = 'auto';
        detailsDiv.style.left = 'calc(100% + 14px)';
    }
}

function hideDetails() {
    const detailsElements = document.querySelectorAll('.popup-game-details');
    detailsElements.forEach(details => {
        const gameUuid = details.id.replace('details-', '');
        clearSlideshowForGameUuid(gameUuid); 
        details.classList.add('hidden');
        details.setAttribute('aria-hidden', 'true');
        details.closest('.game-card-container')?.classList.remove('preview-open');
    });
}
