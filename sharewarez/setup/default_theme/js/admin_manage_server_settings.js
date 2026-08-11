document.addEventListener('DOMContentLoaded', function() {
    console.log("Settings form DOMContentLoaded event triggered.");

    // Initialize tooltips
    var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-toggle="tooltip"]'))
    var tooltipList = tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl)
    });

    const currentSettings = JSON.parse(document.getElementById('currentSettings').textContent);
    console.log("Current settings loaded:", currentSettings);

    const categoryButtons = Array.from(document.querySelectorAll('[data-settings-target]'));
    const settingsPanels = Array.from(document.querySelectorAll('[data-settings-panel]'));
    categoryButtons.forEach(function(button) {
        button.addEventListener('click', function() {
            const target = button.dataset.settingsTarget;
            categoryButtons.forEach(item => {
                const selected = item === button;
                item.classList.toggle('is-active', selected);
                item.setAttribute('aria-selected', selected ? 'true' : 'false');
            });
            settingsPanels.forEach(panel => {
                const selected = panel.dataset.settingsPanel === target;
                panel.classList.toggle('is-active', selected);
                panel.hidden = !selected;
            });
        });
    });

    // Apply current settings to form
    Object.keys(currentSettings).forEach(function(key) {
        const input = document.getElementById(key);
        if (input && input.type === 'checkbox') {
            input.checked = currentSettings[key];
        } else if (input) {
            input.value = currentSettings[key];
        }
        console.log("Applied setting for:", key, "; Value:", currentSettings[key]);
    });

    const mobileNavItems = ['discover', 'library', 'requests', 'downloads', 'favorites'];
    const savedMobileOrder = Array.isArray(currentSettings.mobileNavOrder)
        ? currentSettings.mobileNavOrder
        : mobileNavItems;
    const mobileNavSlots = Array.from(document.querySelectorAll('.mobile-nav-slot'));
    mobileNavSlots.forEach(function(select, index) {
        select.value = savedMobileOrder[index] || mobileNavItems[index];
    });
    function updateMobileNavOptions() {
        const selected = mobileNavSlots.map(select => select.value);
        mobileNavSlots.forEach(function(select) {
            Array.from(select.options).forEach(function(option) {
                option.disabled = option.value !== select.value && selected.includes(option.value);
            });
        });
    }
    mobileNavSlots.forEach(select => select.addEventListener('change', updateMobileNavOptions));
    updateMobileNavOptions();

    // Form submission handler
    document.getElementById('settingsForm').addEventListener('submit', function(e) {
        e.preventDefault();
        console.log("Form submit event triggered.");

        const settings = {
            showSystemLogo: document.getElementById('showSystemLogo').checked,
            showHelpButton: document.getElementById('showHelpButton').checked,
            allowUsersToInviteOthers: document.getElementById('allowUsersToInviteOthers').checked,
            enableWebLinksOnDetailsPage: document.getElementById('enableWebLinksOnDetailsPage').checked,
            enableServerStatusFeature: document.getElementById('enableServerStatusFeature').checked,
            enableNewsletterFeature: document.getElementById('enableNewsletterFeature').checked,
            showVersion: document.getElementById('showVersion').checked,
            showDiscovery: document.getElementById('showDiscovery').checked,
            showFavorites: document.getElementById('showFavorites').checked,
            showTrailers: document.getElementById('showTrailers').checked,
            showPlayStatus: document.getElementById('showPlayStatus').checked,
            enableDeleteGameOnDisk: document.getElementById('enableDeleteGameOnDisk').checked,
            enableGameUpdates: document.getElementById('enableGameUpdates').checked,
            enableGameExtras: document.getElementById('enableGameExtras').checked,
            updateFolderName: document.getElementById('updateFolderName').value,
            extrasFolderName: document.getElementById('extrasFolderName').value,
            siteUrl: document.getElementById('siteUrl').value,
            useTurboImageDownloads: document.getElementById('useTurboImageDownloads').checked,
            turboDownloadThreads: parseInt(document.getElementById('turboDownloadThreads').value),
            turboDownloadBatchSize: parseInt(document.getElementById('turboDownloadBatchSize').value),
            maxConcurrentDownloadsPerUser: parseInt(document.getElementById('maxConcurrentDownloadsPerUser').value),
            downloadBandwidthLimitMbps: parseFloat(document.getElementById('downloadBandwidthLimitMbps').value),
            defaultMonthlyDownloadQuotaGb: parseFloat(document.getElementById('defaultMonthlyDownloadQuotaGb').value),
            downloadQueueWaitSeconds: parseInt(document.getElementById('downloadQueueWaitSeconds').value),
            scanThreadCount: parseInt(document.getElementById('scanThreadCount').value),
            enableHltbIntegration: document.getElementById('enableHltbIntegration').checked,
            hltbRateLimitDelay: parseFloat(document.getElementById('hltbRateLimitDelay').value),
            useLocalMetadata: document.getElementById('useLocalMetadata').checked,
            writeLocalMetadata: document.getElementById('writeLocalMetadata').checked,
            useLocalImages: document.getElementById('useLocalImages').checked,
            localMetadataFilename: document.getElementById('localMetadataFilename').value,
            enableGameRequests: document.getElementById('enableGameRequests').checked,
            allowRequestNotes: document.getElementById('allowRequestNotes').checked,
            allowRequestAnyEdition: document.getElementById('allowRequestAnyEdition').checked,
            maxActiveRequestsPerUser: parseInt(document.getElementById('maxActiveRequestsPerUser').value),
            notifyRequesterRequestEmail: document.getElementById('notifyRequesterRequestEmail').checked,
            notifyAdminRequestEmail: document.getElementById('notifyAdminRequestEmail').checked,
            notifyDiscordNewRequests: document.getElementById('notifyDiscordNewRequests').checked,
            notifyDiscordRequestUpdates: document.getElementById('notifyDiscordRequestUpdates').checked,
            mobileNavOrder: (function() {
                const pinned = mobileNavSlots.map(select => select.value);
                return pinned.concat(mobileNavItems.filter(item => !pinned.includes(item)));
            })()
        };
        if (new Set(settings.mobileNavOrder).size !== mobileNavItems.length) {
            alert('Each mobile navigation position must use a different destination.');
            return;
        }
        console.log("Settings to be saved:", settings);

        fetch('/admin/settings', {
            method: 'POST',
            headers: CSRFUtils.getHeaders({
                'Content-Type': 'application/json'
            }),
            body: JSON.stringify(settings)
        })
        .then(response => {
            console.log("Fetch response received.");
            if (response.ok) {
                return response.json();
            }
            throw new Error('Network response was not ok.');
        })
        .then(data => {
            console.log("Response data:", data);
            document.getElementById('settingsSavedNotification').style.display = 'block';
            setTimeout(() => {
                document.getElementById('settingsSavedNotification').style.display = 'none';
            }, 3000);
        })
        .catch(error => {
            console.error('Fetch operation error:', error);
            alert('Error updating settings');
        });
    });
});
