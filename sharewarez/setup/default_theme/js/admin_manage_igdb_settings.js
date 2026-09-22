document.addEventListener('DOMContentLoaded', function() {
    // Initialize collapse functionality for instructions panel
    const instructionsPanel = document.getElementById('instructionsPanel');
    const toggleIcon = document.getElementById('toggleIcon');
    
    if (instructionsPanel) {
        instructionsPanel.addEventListener('show.bs.collapse', function () {
            toggleIcon.classList.remove('fa-chevron-down');
            toggleIcon.classList.add('fa-chevron-up');
        });
        
        instructionsPanel.addEventListener('hide.bs.collapse', function () {
            toggleIcon.classList.remove('fa-chevron-up');
            toggleIcon.classList.add('fa-chevron-down');
        });
    }

    window.saveMetadataSettings = function() {
        const clientId = document.getElementById('igdb_client_id').value;
        const clientSecret = document.getElementById('igdb_client_secret').value;
        const data = {
            igdb_client_id: clientId,
            igdb_client_secret: clientSecret,
            rawg_api_key: document.getElementById('rawg_api_key').value,
            rawg_enabled: document.getElementById('rawg_enabled').checked,
            metadata_provider_order: document.getElementById('metadata_provider_order').value.split(',')
        };

        fetch('/admin/integrations/metadata/save', {
            method: 'POST',
            headers: CSRFUtils.getHeaders({
                'Content-Type': 'application/json'
            }),
            body: JSON.stringify(data)
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                $.notify(data.message, "success");
            } else {
                $.notify(data.message, "error");
            }
        })
        .catch(error => {
            $.notify("Error saving metadata settings: " + error, "error");
        });
    };

    // Define test settings function
    window.testIgdbSettings = function() {
        const testButton = document.getElementById('testIgdbButton');
        const spinner = document.getElementById('loadingSpinner');
        spinner.style.display = 'flex';  // Changed from 'block' to 'flex'
        const originalText = testButton.textContent;
        testButton.disabled = true;
        
        fetch('/admin/test_igdb', {
            method: 'POST',
            headers: CSRFUtils.getHeaders({
                'Content-Type': 'application/json'
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                $.notify("IGDB API test successful", "success");
                setTimeout(() => location.reload(), 2000);
            } else {
                $.notify("IGDB API test failed: " + data.message, "error");
            }
        })
        .catch(error => {
            $.notify("Error testing IGDB API: " + error, "error");
        })
        .finally(() => {
            testButton.disabled = false;
            spinner.style.display = 'none';
            testButton.textContent = originalText;
        });
    };

    window.testRawgSettings = function() {
        const testButton = document.getElementById('testRawgButton');
        const spinner = document.getElementById('loadingSpinner');
        spinner.style.display = 'flex';
        testButton.disabled = true;
        fetch('/admin/integrations/rawg/test', {
            method: 'POST',
            headers: CSRFUtils.getHeaders({'Content-Type': 'application/json'})
        })
        .then(response => response.json())
        .then(data => $.notify(data.message, data.status === 'success' ? 'success' : 'error'))
        .catch(error => $.notify("Error testing RAWG API: " + error, "error"))
        .finally(() => {
            testButton.disabled = false;
            spinner.style.display = 'none';
        });
    };

});
