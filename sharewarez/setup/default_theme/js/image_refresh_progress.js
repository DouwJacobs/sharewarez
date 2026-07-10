/**
 * Image Refresh Progress Handler
 * Monitors and displays progress for image refresh operations
 */

(function() {
    'use strict';

    // Check if there's an image refresh in progress on page load
    document.addEventListener('DOMContentLoaded', function() {
        // Check if there's an image-refresh flash message (using the new toast class)
        const imageRefreshAlert = document.querySelector('.sw-toast-image-refresh');

        if (imageRefreshAlert) {
            // Get the game UUID from the session (we'll need to pass it via data attribute)
            const gameUuid = imageRefreshAlert.dataset.gameUuid;

            if (gameUuid) {
                startProgressTracking(imageRefreshAlert, gameUuid);
            }
        }
    });

    function startProgressTracking(toastElement, gameUuid) {
        // Create and append the spinner SVG to the toast body
        const spinner = createSpinner();
        const toastBody = toastElement.querySelector('.sw-toast-body');
        const toastHeader = toastElement.querySelector('.sw-toast-header');
        
        if (toastBody) {
            // Add a container for text + spinner to keep them aligned
            const textSpan = document.createElement('span');
            textSpan.textContent = toastBody.textContent;
            toastBody.innerHTML = '';
            toastBody.style.display = 'flex';
            toastBody.style.alignItems = 'center';
            toastBody.style.justifyContent = 'space-between';
            toastBody.appendChild(textSpan);
            toastBody.appendChild(spinner);
        }

        let pollCount = 0;
        const maxPolls = 120; // 2 minutes max (120 * 1000ms)

        function updateToast(type, headerText, bodyText) {
            toastElement.classList.remove('sw-toast-image-refresh', 'sw-toast-danger', 'sw-toast-success', 'sw-toast-warning');
            toastElement.classList.add('sw-toast-' + type);
            
            if (toastHeader) {
                toastHeader.classList.remove('sw-toast-header-image-refresh', 'sw-toast-header-danger', 'sw-toast-header-success', 'sw-toast-header-warning');
                toastHeader.classList.add('sw-toast-header-' + type);
                const title = toastHeader.querySelector('strong');
                if (title) title.textContent = headerText;
                
                // Update icon
                const icon = toastHeader.querySelector('i');
                if (icon) {
                    icon.className = 'fas me-2 ' + (type === 'success' ? 'fa-check-circle' : (type === 'danger' || type === 'warning' ? 'fa-exclamation-triangle' : 'fa-info-circle'));
                }
            }
            
            if (toastBody) {
                toastBody.textContent = bodyText; // This also removes the spinner
            }
        }

        const pollInterval = setInterval(function() {
            pollCount++;

            fetch(`/check_image_refresh_progress/${gameUuid}`, {
                method: 'GET',
                headers: CSRFUtils.getHeaders({
                    'X-Requested-With': 'XMLHttpRequest'
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'complete') {
                    // Update progress to 100%
                    updateSpinnerProgress(spinner, 100);

                    // Wait a moment to show completion, then update message
                    setTimeout(function() {
                        updateToast('success', 'Success', 'Game updated, images downloaded successfully');

                        // Remove the toast after 3 seconds by utilizing Bootstrap's hide method or custom animation
                        setTimeout(function() {
                            toastElement.classList.add('hiding');
                            setTimeout(function() {
                                toastElement.remove();
                            }, 300);
                        }, 3000);
                    }, 500);

                    clearInterval(pollInterval);
                } else if (data.status === 'error') {
                    updateToast('danger', 'Error', 'Failed to refresh game images');
                    spinner.remove();
                    clearInterval(pollInterval);
                } else if (data.status === 'in_progress') {
                    // Update the progress circle
                    updateSpinnerProgress(spinner, data.progress || 0);
                } else if (data.status === 'not_found' && pollCount > 5) {
                    // If not found after 5 polls, assume it completed
                    updateToast('success', 'Success', 'Game updated successfully');
                    spinner.remove();
                    clearInterval(pollInterval);
                }

                // Stop polling after max attempts
                if (pollCount >= maxPolls) {
                    updateToast('warning', 'Warning', 'Image refresh is taking longer than expected');
                    spinner.remove();
                    clearInterval(pollInterval);
                }
            })
            .catch(error => {
                console.error('Error checking progress:', error);
                // Don't stop polling on network errors, might be temporary
            });
        }, 1000); // Poll every second
    }

    function createSpinner() {
        const spinner = document.createElement('span');
        spinner.className = 'image-refresh-spinner';
        spinner.innerHTML = `
            <svg viewBox="0 0 22 22">
                <circle class="spinner-circle-bg" cx="11" cy="11" r="10"></circle>
                <circle class="spinner-circle-progress" cx="11" cy="11" r="10"></circle>
            </svg>
        `;
        return spinner;
    }

    function updateSpinnerProgress(spinner, progress) {
        const circle = spinner.querySelector('.spinner-circle-progress');
        if (circle) {
            // Calculate stroke-dashoffset based on progress
            // Circle circumference = 2 * PI * r = 2 * 3.14159 * 10 = 62.83
            const circumference = 62.83;
            const offset = circumference - (progress / 100) * circumference;
            circle.style.strokeDashoffset = offset;
        }
    }
})();
