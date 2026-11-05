import { fileIcons } from './config/file_type_icons.js';

function showSpinner() {
    document.getElementById('globalSpinner').hidden = false;
}

function hideSpinner() {
    document.getElementById('globalSpinner').hidden = true;
}

function attachDeleteFolderFormListeners() {
    document.querySelectorAll('.delete-folder-form').forEach(form => {
        if (!form.dataset.listenerAdded) {
            form.addEventListener('submit', function(event) {
                event.preventDefault();
                const folderPath = form.querySelector('[name="folder_path"]').value;
                
                // Add confirmation dialog
                if (!confirm(`Are you sure you want to delete the folder ${folderPath} FROM DISK?`)) {
                    console.log("Deletion cancelled by user");
                    return; // Exit the function if user cancels
                }

                showSpinner();
                const csrfToken = CSRFUtils.getToken();

                console.log("Attempting to delete folder with path:", folderPath);

                fetch('/delete_folder', {
                    method: 'POST',
                    headers: CSRFUtils.getHeaders({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({folder_path: folderPath})
                })
                .then(response => response.json())
                .then(data => {
                    console.log("Server response:", data);

                    if(data.status === 'success') {
                        console.log("Deletion successful, removing row.");
                        form.closest('tr').remove();
                    } else {
                        console.log("Deletion not successful:", data.message);
                        if (data.message === "The specified path does not exist or is not a folder. Entry removed if it was in the database.") {
                            console.log("Folder does not exist, removing row.");
                            form.closest('tr').remove();
                        }
                    }
                    alert(data.message);
                })
                .catch(error => {
                    console.error('Fetch error:', error);
                })
                .finally(() => {
                    hideSpinner();
                });
            });
            form.dataset.listenerAdded = 'true';
        }
    });
}

document.addEventListener('DOMContentLoaded', function() {
    console.log("Document loaded. Setting up form submission handlers and tab activation based on activeTab.");

    // Initialize tooltips
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-toggle="tooltip"]'))
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl)
    })

    // Simple table references - no DataTables initialization needed
    const scanJobsTableBody = document.getElementById('jobsTableBody');
    const unmatchedTableBody = document.getElementById('unmatchedFoldersTableBody');

    const urlParams = new URLSearchParams(window.location.search);
    const urlActiveTab = urlParams.get('active_tab');
    const metaActiveTab = document.querySelector('meta[name="active-tab"]').getAttribute('content');
    const storedActiveTab = localStorage.getItem('scan_management_active_tab');

    // Priority: URL parameter > localStorage > meta tag > default 'auto'
    const activeTab = urlActiveTab || storedActiveTab || metaActiveTab || 'auto';
    console.log("Active tab determined:", activeTab, {urlActiveTab, storedActiveTab, metaActiveTab});

    switch (activeTab) {
        case 'manual':
            console.log("Activating manualScan tab.");
            new bootstrap.Tab(document.querySelector('#manualScan-tab')).show();
            break;
        case 'unmatched':
            console.log("Activating unmatchedFolders tab.");
            new bootstrap.Tab(document.querySelector('#unmatchedFolders-tab')).show();
            break;
        case 'scan_filters':
            console.log("Activating scanFilters tab.");
            new bootstrap.Tab(document.querySelector('#scanFilters-tab')).show();
            break;
        case 'file_extensions':
            console.log("Activating fileExtensions tab.");
            new bootstrap.Tab(document.querySelector('#fileExtensions-tab')).show();
            break;
        case 'image_queue':
            console.log("Activating imageQueue tab.");
            new bootstrap.Tab(document.querySelector('#imageQueue-tab')).show();
            break;
        case 'deleteLibrary':
            console.log("Activating deleteLibrary tab.");
            new bootstrap.Tab(document.querySelector('#deleteLibrary-tab')).show();
            break;
        default:
            console.log("Defaulting to activating autoScan tab.");
            new bootstrap.Tab(document.querySelector('#autoScan-tab')).show();
    }

    // Add event listeners to all tab links to update URL and localStorage when clicked
    document.querySelectorAll('.admin_manage_scanjobs-nav-tabs .nav-link').forEach(tab => {
        tab.addEventListener('shown.bs.tab', function(event) {
            const tabId = event.target.getAttribute('href').substring(1); // Remove # from href
            let activeTabValue = 'auto';

            switch(tabId) {
                case 'manualScan':
                    activeTabValue = 'manual';
                    break;
                case 'unmatchedFolders':
                    activeTabValue = 'unmatched';
                    break;
                case 'scanFilters':
                    activeTabValue = 'scan_filters';
                    break;
                case 'fileExtensions':
                    activeTabValue = 'file_extensions';
                    break;
                case 'imageQueue':
                    activeTabValue = 'image_queue';
                    break;
                default:
                    activeTabValue = 'auto';
            }

            // Store in localStorage for persistence
            localStorage.setItem('scan_management_active_tab', activeTabValue);

            // Update URL without page reload
            const url = new URL(window.location.href);
            url.searchParams.set('active_tab', activeTabValue);
            window.history.replaceState({}, '', url.toString());
        });
    });

    // Native Enter and button activation submit the same hidden form action.
    const manualScanForm = document.querySelector('#manualScan form');
    if (manualScanForm) {
        manualScanForm.addEventListener('submit', function(event) {
            if (manualScanForm.getAttribute('aria-busy') === 'true') {
                event.preventDefault();
                return;
            }

            const submitButton = document.getElementById('manualScanSubmitBtn');
            const progress = document.getElementById('manualScanProgress');
            const browseButton = document.getElementById('browseFoldersBtnManual');

            submitButton.disabled = true;
            browseButton.disabled = true;
            manualScanForm.setAttribute('aria-busy', 'true');
            progress.hidden = false;
        });
    }

    setupFolderBrowse('#browseFoldersBtn', '#folderContents', '#loadingSpinner', '#upFolderBtn', '#folder_path');
    setupFolderBrowse('#browseFoldersBtnManual', '#folderContentsManual', '#loadingSpinnerManual', '#upFolderBtnManual', '#manualFolderPath');

    // No complex toggle functionality needed for simplified table

    var csrfToken = CSRFUtils.getToken();

    // Helper function to get user-friendly status display
    function getDisplayStatus(job) {
        if (job.status === 'Failed' && job.error_message) {
            if (job.error_message === 'Scan cancelled by user') {
                return 'Cancelled';
            } else if (job.error_message === 'Scan job interrupted by server restart') {
                return 'Interrupted by server restart';
            }
        }
        return job.status;
    }

    const activeScanStatuses = new Set(['Running', 'Stopping']);
    let scanJobsPollTimer = null;
    let scanJobsPollInFlight = false;

    const isAutoScanTabVisible = () =>
        document.querySelector('#autoScan')?.classList.contains('active') && !document.hidden;

    const stopScanJobsPolling = () => {
        if (scanJobsPollTimer) {
            window.clearTimeout(scanJobsPollTimer);
            scanJobsPollTimer = null;
        }
    };

    const updateScanJobs = () => {
        if (scanJobsPollInFlight) {
            return Promise.resolve(false);
        }

        scanJobsPollInFlight = true;
        return fetch('/api/scan_jobs_status', {cache: 'no-store'})
            .then(response => response.json())
            .then(data => {
                // Sort the data array to ensure the latest scan is at the top
                data.sort((a, b) => new Date(b.last_run) - new Date(a.last_run));
                
                // Clear the table body
                scanJobsTableBody.innerHTML = '';

                if (data.length === 0) {
                    scanJobsTableBody.innerHTML = `
                        <tr class="scan-empty-state-row">
                            <td colspan="6"><div class="scan-empty-state"><i class="fas fa-inbox" aria-hidden="true"></i><strong>No scan jobs yet</strong><span>Started scans will appear here.</span></div></td>
                        </tr>`;
                    return false;
                }
                
                const isAnyJobRunning = data.some(job => activeScanStatuses.has(job.status));
                
                data.forEach(job => {
                    // Create progress column content
                    let progressColumn = '';
                    if (job.status === 'Running' && job.total_folders > 0) {
                        const percentage = job.progress_percentage || 0;
                        const processed = job.folders_success + job.folders_failed;
                        progressColumn = `
                            <div class="scan-progress">
                                <div class="progress mb-1">
                                    <div class="progress-bar" style="width: ${percentage}%"></div>
                                </div>
                                <div class="progress-info">
                                    <span class="progress-numbers">${processed}/${job.total_folders} (${percentage}%)</span>
                                </div>
                                <div class="progress-status">
                                    <small class="text-bright-green">${job.current_processing || 'Processing...'}</small>
                                </div>
                            </div>
                        `;
                    } else if (job.status === 'Stopping') {
                        const processed = job.folders_success + job.folders_failed;
                        progressColumn = `
                            <div class="scan-progress">
                                <div class="progress-status">
                                    <span class="text-warning">
                                        <i class="fas fa-spinner fa-spin"></i>
                                        Stopping scan... (${processed}/${job.total_folders})
                                    </span>
                                </div>
                                <div class="progress-status">
                                    <small class="text-muted">Waiting for threads to complete</small>
                                </div>
                            </div>
                        `;
                    } else if (job.status === 'Completed') {
                        progressColumn = `<span class="text-success"><i class="fas fa-check"></i> ${job.folders_success + job.folders_failed}/${job.total_folders}</span>`;
                    } else if (job.status === 'Failed') {
                        progressColumn = `<span class="text-danger"><i class="fas fa-times"></i> ${job.folders_success + job.folders_failed}/${job.total_folders}</span>`;
                    } else {
                        progressColumn = '-';
                    }

                    // Create actions column content
                    const actionsColumn = `
                        ${job.status === 'Running' ?
                            `<form action="/cancel_scan_job/${job.id}" method="post" class="inline-form">
                                <input type="hidden" name="csrf_token" value="${csrfToken}">
                                <button type="submit" class="btn btn-warning btn-sm" title="Cancel Scan" aria-label="Cancel scan"><i class="fas fa-stop" aria-hidden="true"></i></button>
                            </form>` :
                        job.status === 'Stopping' ?
                            `<button class="btn btn-warning btn-sm" disabled title="Scan is stopping, please wait..." aria-label="Scan is stopping">
                                <i class="fas fa-spinner fa-spin" aria-hidden="true"></i>
                            </button>` :
                            `${isAnyJobRunning ?
                                `<button class="btn btn-secondary btn-sm" disabled title="Cannot restart while another scan is running" aria-label="Restart unavailable while another scan is running"><i class="fas fa-sync" aria-hidden="true"></i></button>` :
                                `<form action="/restart_scan_job/${job.id}" method="post" class="inline-form">
                                    <input type="hidden" name="csrf_token" value="${csrfToken}">
                                        <button type="submit" class="btn btn-secondary btn-sm" title="Restart Scan" aria-label="Restart scan"><i class="fas fa-sync" aria-hidden="true"></i></button>
                                </form>`
                            }`
                        }
                    `;
                    
                    const row = document.createElement('tr');
                    row.innerHTML = `
                        <td data-label="ID">${job.id.substring(0, 8)}</td>
                        <td data-label="Library">${job.library_name || 'N/A'}</td>
                        <td data-label="Path">${job.scan_folder || 'N/A'}</td>
                        <td data-label="Status">${getDisplayStatus(job)}</td>
                        <td data-label="Progress">${progressColumn}</td>
                        <td data-label="Actions" class="scan-row-actions">${actionsColumn}</td>
                    `;
                    scanJobsTableBody.appendChild(row);
                });

                return isAnyJobRunning;
            })
            .catch(error => {
                console.error('Error fetching scan jobs status:', error);
                return false;
            })
            .finally(() => {
                scanJobsPollInFlight = false;
            });
    };

    const refreshScanJobs = () => {
        stopScanJobsPolling();

        if (!isAutoScanTabVisible()) {
            return;
        }

        updateScanJobs().then(isAnyJobRunning => {
            if (!isAnyJobRunning || !isAutoScanTabVisible()) {
                return;
            }

            scanJobsPollTimer = window.setTimeout(refreshScanJobs, 3000);
        });
    };

    const updateUnmatchedFolders = () => {
        showSpinner();
        return fetch('/api/unmatched_folders', {cache: 'no-store'})
            .then(response => response.json())
            .then(data => {
                // Clear the table body
                unmatchedTableBody.innerHTML = '';

                if (data.length === 0) {
                    unmatchedTableBody.innerHTML = `
                        <tr class="scan-empty-state-row">
                            <td colspan="5"><div class="scan-empty-state"><i class="fas fa-circle-check" aria-hidden="true"></i><strong>No unmatched folders</strong><span>Folders that need identification will appear here.</span></div></td>
                        </tr>`;
                    return;
                }
                
                data.forEach(folder => {
                    const actionsColumn = `
                        <button 
                            onclick="window.toggleIgnoreStatus('${folder.id}', this)" 
                            class="btn ${folder.status === 'Ignore' ? 'btn-warning' : 'btn-secondary'} btn-sm"
                            title="Ignored folders are not scanned"
                            aria-label="${folder.status === 'Ignore' ? 'Resume scanning this folder' : 'Ignore this folder'}">
                            <i class="fas ${folder.status === 'Ignore' ? 'fa-eye-slash' : 'fa-eye'}" aria-hidden="true"></i>
                        </button>
                        <button onclick="clearEntry('${folder.id}', this)" class="btn btn-secondary btn-sm" title="Remove from unmatched list" aria-label="Remove from unmatched list"><i class="fas fa-eraser" aria-hidden="true"></i></button>
                        <form class="delete-folder-form inline-form">
                            <input type="hidden" name="csrf_token" value="${csrfToken}">
                            <input type="hidden" name="folder_path" value="${folder.folder_path}">
                            <button type="submit" class="btn btn-danger btn-sm" title="Delete the folder from disk" aria-label="Delete folder from disk"><i class="fas fa-trash-alt" aria-hidden="true"></i></button>
                        </form>
                        <form action="/add_game_manual" method="GET" class="inline-form">
                            <input type="hidden" name="full_disk_path" value="${folder.folder_path}">
                            <input type="hidden" name="library_uuid" value="${folder.library_uuid}">
                            <input type="hidden" name="platform_name" value="${folder.platform_name}">
                            <input type="hidden" name="platform_id" value="${folder.platform_id}">
                            <input type="hidden" name="from_unmatched" value="true">
                            <button type="submit" class="btn btn-primary btn-sm" title="Attempt manual IGDB search" aria-label="Identify with IGDB"><i class="fas fa-search" aria-hidden="true"></i></button>
                        </form>
                    `;
                    
                    const row = document.createElement('tr');
                    row.setAttribute('data-status', folder.status);
                    row.setAttribute('data-folder-path', folder.folder_path.toLowerCase());
                    row.setAttribute('data-library-name', folder.library_name.toLowerCase());
                    row.setAttribute('data-platform-name', folder.platform_name.toLowerCase());
                    row.innerHTML = `
                        <td data-label="Folder path"><i class="fas fa-folder" aria-hidden="true"></i> ${folder.folder_path}</td>
                        <td data-label="Status"><span class="status-${folder.status.toLowerCase()}">${folder.status}</span></td>
                        <td data-label="Library">${folder.library_name}</td>
                        <td data-label="Platform">${folder.platform_name}</td>
                        <td data-label="Actions" class="scan-row-actions">${actionsColumn}</td>
                    `;
                    unmatchedTableBody.appendChild(row);
                });
                // Attach event listeners to the new forms
                attachDeleteFolderFormListeners();

                // Update results counter after data load
                updateResultsCounter();
            })
            .catch(error => {
                console.error('Error fetching unmatched folders:', error);
            })
            .finally(() => {
                hideSpinner();
            });
    };

    // Filtering functionality
    let currentFilter = 'all';
    let currentSearch = '';

    // Notification system
    function showSuccessNotification(message) {
        // Remove any existing notification
        const existingNotification = document.querySelector('.success-notification');
        if (existingNotification) {
            existingNotification.remove();
        }

        // Create new notification
        const notification = document.createElement('div');
        notification.className = 'success-notification';
        notification.innerHTML = `
            <i class="fas fa-check-circle"></i>
            <span>${message}</span>
        `;

        document.body.appendChild(notification);

        // Show notification
        setTimeout(() => notification.classList.add('show'), 10);

        // Hide and remove notification after 3 seconds
        setTimeout(() => {
            notification.classList.add('hide');
            setTimeout(() => notification.remove(), 300);
        }, 3000);
    }

    function filterUnmatchedRows() {
        const unmatchedRows = document.querySelectorAll('#unmatchedFoldersTableBody tr:not(.scan-empty-state-row)');
        let visibleCount = 0;

        unmatchedRows.forEach(row => {
            const status = row.getAttribute('data-status');
            const folderPath = row.getAttribute('data-folder-path') || '';
            const libraryName = row.getAttribute('data-library-name') || '';
            const platformName = row.getAttribute('data-platform-name') || '';

            // Check status filter
            const statusMatch = currentFilter === 'all' || status === currentFilter;

            // Check search filter
            const searchMatch = currentSearch === '' ||
                folderPath.includes(currentSearch) ||
                libraryName.includes(currentSearch) ||
                platformName.includes(currentSearch);

            // Special handling for ignored items
            let shouldShow = statusMatch && searchMatch;

            // For Option 2 behavior: Hide ignored items unless viewing "All" or "Ignored"
            if (status === 'Ignore' && currentFilter !== 'all' && currentFilter !== 'Ignore') {
                shouldShow = false;
            }

            if (shouldShow) {
                row.style.display = '';
                row.classList.remove('row-fade-out'); // Remove fade-out class if present
                visibleCount++;
            } else {
                row.style.display = 'none';
            }
        });

        updateResultsCounter(visibleCount, unmatchedRows.length);
    }

    function updateResultsCounter(visible = null, total = null) {
        const resultsInfo = document.getElementById('resultsInfo');
        if (!resultsInfo) return;

        if (visible === null || total === null) {
            const unmatchedRows = document.querySelectorAll('#unmatchedFoldersTableBody tr:not(.scan-empty-state-row)');
            total = unmatchedRows.length;
            visible = Array.from(unmatchedRows).filter(row => row.style.display !== 'none').length;
        }

        if (currentFilter === 'all' && currentSearch === '') {
            resultsInfo.textContent = `Showing all ${total} entries`;
        } else {
            const filterText = currentFilter !== 'all' ? ` (${currentFilter})` : '';
            const searchText = currentSearch ? ` matching "${currentSearch}"` : '';
            resultsInfo.textContent = `Showing ${visible} of ${total} entries${filterText}${searchText}`;
        }
    }

    function setupUnmatchedFilters() {
        // Filter button event listeners
        document.querySelectorAll('.filter-btn').forEach(btn => {
            btn.addEventListener('click', function() {
                // Remove active class from all buttons
                document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));

                // Add active class to clicked button
                this.classList.add('active');

                // Update current filter
                currentFilter = this.getAttribute('data-filter');

                // Apply filtering
                filterUnmatchedRows();
            });
        });

        // Search input event listener
        const searchInput = document.getElementById('unmatchedSearch');
        if (searchInput) {
            searchInput.addEventListener('input', function() {
                currentSearch = this.value.toLowerCase();
                filterUnmatchedRows();
            });
        }
    }

    // Set up filter controls
    setupUnmatchedFilters();

    const refreshUnmatchedFolders = () => {
        const unmatchedTab = document.querySelector('#unmatchedFolders');
        if (!unmatchedTab?.classList.contains('active') || document.hidden) {
            return;
        }

        updateUnmatchedFolders().then(filterUnmatchedRows);
    };

    // Load data only for the currently visible tab. A scan job then enables
    // three-second polling until it reaches a terminal status.
    refreshScanJobs();
    refreshUnmatchedFolders();

    document.querySelectorAll('.admin_manage_scanjobs-nav-tabs .nav-link').forEach(tab => {
        tab.addEventListener('shown.bs.tab', event => {
            if (event.target.getAttribute('href') === '#autoScan') {
                refreshScanJobs();
            } else {
                stopScanJobsPolling();
            }

            if (event.target.getAttribute('href') === '#unmatchedFolders') {
                refreshUnmatchedFolders();
            }
        });
    });

    document.addEventListener('visibilitychange', () => {
        if (document.hidden) {
            stopScanJobsPolling();
            return;
        }

        refreshScanJobs();
        refreshUnmatchedFolders();
    });

    // Global functions for table interactions
    window.toggleIgnoreStatus = function(folderId, button) {
        const row = button.closest('tr');
        const currentStatus = row.getAttribute('data-status');
        const isBeingIgnored = currentStatus !== 'Ignore';

        // Show immediate visual feedback
        if (isBeingIgnored) {
            // If we're ignoring the item and not viewing "All" or "Ignored", hide it immediately
            if (currentFilter !== 'all' && currentFilter !== 'Ignore') {
                row.classList.add('row-fade-out');
                setTimeout(() => {
                    row.style.display = 'none';
                    updateResultsCounter();
                }, 300);
            }
        }

        fetch(`/toggle_ignore_status/${folderId}`, {
            method: 'POST',
            headers: CSRFUtils.getHeaders({
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                // Show success notification
                const action = isBeingIgnored ? 'ignored' : 'un-ignored';
                showSuccessNotification(`Folder ${action} successfully`);

                // Update table data in background
                updateUnmatchedFolders().then(() => {
                    // Reapply current filters after data refresh
                    filterUnmatchedRows();
                });
            } else {
                // If there was an error, restore the row if it was hidden
                if (isBeingIgnored && currentFilter !== 'all' && currentFilter !== 'Ignore') {
                    row.classList.remove('row-fade-out');
                    row.style.display = '';
                }
                console.error('Error toggling ignore status:', data.message);
            }
        })
        .catch(error => {
            // If there was an error, restore the row if it was hidden
            if (isBeingIgnored && currentFilter !== 'all' && currentFilter !== 'Ignore') {
                row.classList.remove('row-fade-out');
                row.style.display = '';
            }
            console.error('Error toggling ignore status:', error);
        });
    };

    window.clearEntry = function(folderId, triggerButton) {
        if (confirm('Remove this entry from the unmatched list?')) {
            const row = triggerButton.closest('tr');

            // Immediate visual feedback - fade out the row
            row.classList.add('row-fade-out');
            setTimeout(() => {
                row.style.display = 'none';
                updateResultsCounter();
            }, 300);

            fetch(`/clear_unmatched_entry/${folderId}`, {
                method: 'POST',
                headers: CSRFUtils.getHeaders({
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    showSuccessNotification('Entry removed successfully');

                    // Update table data in background
                    updateUnmatchedFolders().then(() => {
                        // Reapply current filters after data refresh
                        filterUnmatchedRows();
                    });
                } else {
                    // If there was an error, restore the row
                    row.classList.remove('row-fade-out');
                    row.style.display = '';
                    console.error('Error clearing entry:', data.message);
                }
            })
            .catch(error => {
                // If there was an error, restore the row
                row.classList.remove('row-fade-out');
                row.style.display = '';
                console.error('Error clearing entry:', error);
            });
        }
    };
});

// Each picker owns its cursor and request generation. Only a successful latest
// response commits a navigation choice; a failure leaves the form draft intact.
function setupFolderBrowse(browseButtonId, folderContentsId, spinnerId, upButtonId, inputFieldId) {
    const browse = $(browseButtonId);
    const contents = $(folderContentsId);
    const spinner = $(spinnerId);
    const up = $(upButtonId);
    const input = $(inputFieldId);
    const form = input.closest('form');
    let currentPath = '';
    let generation = 0;

    function fetchFolders(path, restoreFocus = false) {
        const requestGeneration = ++generation;
        spinner.prop('hidden', false);
        contents.attr('aria-busy', 'true');
        $.ajax({
            url: '/api/browse_folders_ss',
            data: {path},
            success(data) {
                if (requestGeneration !== generation) return;
                spinner.prop('hidden', true);
                contents.empty().attr('aria-busy', 'false');
                currentPath = data.currentPath || '';
                input.val(currentPath || '.');
                up.prop('hidden', !currentPath);

                const useFolder = $('<button type="button" class="btn btn-secondary">')
                    .text('Use this folder').on('click', () => {
                        input.val(currentPath || '.');
                        input.trigger('focus');
                    });
                contents.append(useFolder);
                if (!data.items.length) {
                    contents.append($('<div class="folder-browser-empty" role="status">')
                        .append($('<strong>').text('No items here')));
                }
                if (data.hasErrors) {
                    contents.append($('<div class="alert alert-warning" role="status">')
                        .text(`Some items (${data.skippedItems}) could not be accessed and were skipped.`));
                }
                data.items.forEach(item => {
                    const itemPath = currentPath + item.name + (item.isDir ? '/' : '');
                    const icon = item.isDir ? 'fa-folder' : (fileIcons[item.ext] || fileIcons.default);
                    const itemElement = $('<button type="button" class="btn btn-secondary">')
                        .addClass(item.isDir ? 'folder-item' : 'file-item')
                        .attr('data-path', itemPath)
                        .append($('<i aria-hidden="true">').addClass(`fas ${icon}`))
                        .append($('<span>').text(item.name));
                    if (item.isDir) {
                        itemElement.on('click', () => fetchFolders(itemPath, true));
                    } else {
                        itemElement.append($('<span class="file-size">').text(`(${formatFileSize(item.size)})`));
                        itemElement.on('click', () => {
                            if (form.find('[name="scan_mode"]:checked').val() !== 'files') {
                                const notice = $('<div class="alert alert-warning" role="status">')
                                    .text('Choose Files mode to select an individual file.');
                                contents.find('.file-mode-notice').remove();
                                contents.append(notice.addClass('file-mode-notice'));
                                return;
                            }
                            input.val(itemPath);
                            contents.find('.active-selection').removeClass('active-selection');
                            itemElement.addClass('active-selection');
                        });
                    }
                    contents.append(itemElement);
                });
                if (restoreFocus) useFolder.trigger('focus');
            },
            error(error) {
                if (requestGeneration !== generation) return;
                spinner.prop('hidden', true);
                contents.attr('aria-busy', 'false');
                const response = error.responseJSON || {};
                const errorState = $('<div class="folder-browser-error" role="alert">')
                    .append($('<strong>').text(response.error || 'Could not browse the scan location.'))
                    .append($('<span>').text(response.detail || 'Check that the directory is mounted and readable.'));
                contents.find('.folder-browser-error').remove();
                contents.append(errorState);
                // Keep existing controls and focus available for retry.
            }
        });
    }

    browse.on('click', () => fetchFolders(''));
    up.on('click', () => {
        const segments = currentPath.split('/').filter(Boolean);
        segments.pop();
        fetchFolders(segments.length ? segments.join('/') + '/' : '', true);
    });
}

function formatFileSize(bytes) {
    if (bytes === 0) return '0 Bytes';
    const kilobyte = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(kilobyte));
    return parseFloat((bytes / Math.pow(kilobyte, i)).toFixed(2)) + ' ' + sizes[i];
}
