document.addEventListener('DOMContentLoaded', function() {
    // #content keeps a transform after its entrance animation, which makes fixed
    // descendants use the content panel as their containing block. Portal the
    // save overlay to body so it always covers and centers in the true viewport.
    const saveOverlay = document.getElementById('saveSpinner');
    if (saveOverlay && saveOverlay.parentElement !== document.body) {
        document.body.appendChild(saveOverlay);
    }

    var platformDisplay = document.querySelector('#platform_display');
    const platformId = document.querySelector('#platform_id').textContent; 
    const igdbIdInput = document.querySelector('#igdb_id');
    const fullPathInput = document.querySelector('#full_disk_path');
    const nameInput = document.querySelector('#name');
    const urlInput = document.querySelector('#url');
    const submitButton = document.querySelector('button[type="submit"]');
    const igdbIdFeedback = document.querySelector('#igdb_id_feedback');
    const fullPathFeedback = document.createElement('small');
    const igdbIdSearchButton = document.querySelector('#search-igdb-btn');
    const igdbNameSearchButton = document.querySelector('#search-igdb');
    const igdbIdSearchStatus = document.querySelector('#igdb-id-search-status');
    const igdbNameSearchStatus = document.querySelector('#igdb-name-search-status');

    function setSearchLoading(button, statusElement, isLoading, message = '') {
        if (isLoading) {
            button.dataset.defaultContent = button.innerHTML;
            button.disabled = true;
            button.setAttribute('aria-busy', 'true');
            button.innerHTML = `<span class="button-spinner" aria-hidden="true"></span>${message}`;
            statusElement.textContent = '';
            statusElement.classList.add('is-loading');
            return;
        }

        button.disabled = false;
        button.removeAttribute('aria-busy');
        button.innerHTML = button.dataset.defaultContent || button.innerHTML;
        statusElement.classList.remove('is-loading');
    }

    // Function to fetch the next available custom IGDB ID
    async function fetchNextCustomIgdbId() {
        try {
            const response = await fetch('/api/get_next_custom_igdb_id');
            const data = await response.json();
            if (data.error) {
                console.error('Error fetching next custom IGDB ID:', data.error);
                return 2000000420; // Fallback to base value if API fails
            }
            return data.next_id;
        } catch (error) {
            console.error('Error fetching next custom IGDB ID:', error);
            return 2000000420; // Fallback to base value if API fails
        }
    }

    // Add Non-Existing Game button handler
    document.querySelector('#add-non-existing-game').addEventListener('click', async function() {
        // Disable IGDB search functionality
        document.querySelector('#search-igdb-btn').disabled = true;
        document.querySelector('#search-igdb').disabled = true;
        igdbIdInput.value = await fetchNextCustomIgdbId();
        igdbIdInput.readOnly = true;

        // Clear and enable name field
        nameInput.value = '';
        nameInput.readOnly = false;
        nameInput.focus();

        // Expand details section
        const gameDetailsCollapse = document.querySelector('#gameDetails');
        if (gameDetailsCollapse) {
            const bootstrapCollapse = new bootstrap.Collapse(gameDetailsCollapse, {
                show: true
            });
        }
    });

    fullPathFeedback.id = 'full_disk_path_feedback';
    fullPathInput.parentNode.insertBefore(fullPathFeedback, fullPathInput.nextSibling);

    $(submitButton).tooltip({
        title: "Incomplete entry",
        placement: "top",
        trigger: "hover"
    });

    function updateButtonState(isDisabled) {
        console.log(`Update submit button state: ${isDisabled ? 'Disabled' : 'Enabled'}`);
        submitButton.disabled = isDisabled;
        if (isDisabled) {
            $(submitButton).tooltip('enable');
        } else {
            $(submitButton).tooltip('disable');
        }
    }

    function validateField(inputElement, isValid) {
        if (isValid) {
            console.log(`${inputElement.id} is valid`);
            inputElement.classList.remove('invalid-input');
        } else {
            console.log(`${inputElement.id} is invalid`);
            inputElement.classList.add('invalid-input');
        }
    }

    function checkFieldsAndToggleSubmit() {
        const igdbIdIsValid = igdbIdInput.value.trim().length > 0 && /^\d+$/.test(igdbIdInput.value);
        const fullPathIsValid = fullPathInput.value.trim().length > 0;
        const nameIsValid = nameInput.value.trim().length > 0;
        const libraryUuidIsValid = libraryUuidInput.value.trim().length > 0;

        validateField(igdbIdInput, igdbIdIsValid);
        validateField(fullPathInput, fullPathIsValid);
        validateField(nameInput, nameIsValid);
        validateField(libraryUuidInput, libraryUuidIsValid);

        updateButtonState(!(igdbIdIsValid && fullPathIsValid && nameIsValid && libraryUuidIsValid));
    }

    function updateFormWithGameData(gameData) {
        console.log("Received game data:", gameData); // Print out the gameData object
        function updateMultiSelect(containerId, values) {
            const checkboxes = document.querySelectorAll(`${containerId} input[type="checkbox"]`);
            const selectedNames = new Set((values || []).map(value =>
                (typeof value === 'string' ? value : value.name || '').trim().toLowerCase()
            ));
            checkboxes.forEach(checkbox => {
                const label = checkbox.closest('label');
                const name = label ? label.textContent.trim().toLowerCase() : '';
                checkbox.checked = selectedNames.has(name);
            });
        }

        updateMultiSelect('#genres-container', gameData.genres);
        updateMultiSelect('#gamemodes-container', gameData.game_modes);
        updateMultiSelect('#themes-container', gameData.themes);
        updateMultiSelect('#platforms-container', gameData.platforms);
        updateMultiSelect('#perspectives-container', gameData.player_perspectives);

        // Update Category select field - using original field names to match scanning code
        const categorySelect = document.querySelector('#category'); // Assuming #category is the ID of the select
        if (gameData.category !== undefined && categorySelect) {
            // Map IGDB category ID to select option value
            categorySelect.value = gameData.category; // Direct numeric mapping
        }

        // Update Status select field - using original field names to match scanning code
        const statusSelect = document.querySelector('#status'); // Assuming #status is the ID of the select
        if (gameData.status !== undefined && statusSelect) {
            // Map IGDB status ID to select option value
            statusSelect.value = gameData.status; // Direct numeric mapping
        }

        // Assuming gameData.involved_companies is an array of company IDs
        if (gameData.involved_companies && gameData.involved_companies.length > 0) {
            // Map each companyId to a fetch promise
            const companyFetchPromises = gameData.involved_companies.map(companyId =>
                fetch(`/api/get_company_role?game_igdb_id=${gameData.id}&company_id=${companyId}`)
                    .then(response => response.json())
            );

            // Wait for all fetch promises to resolve
            Promise.all(companyFetchPromises)
                .then(results => {
                    // Flags to check if we found any developer or publisher
                    let foundDeveloper = false;
                    let foundPublisher = false;

                    results.forEach(data => {
                        if (data.error) {
                            console.error('Error:', data.error);
                        } else {
                            // Check the role and update the corresponding field
                            if (data.role === 'Developer') {
                                const developerInput = document.querySelector('#developer');
                                developerInput.value = data.company_name;
                                foundDeveloper = true;
                            } else if (data.role === 'Publisher') {
                                const publisherInput = document.querySelector('#publisher');
                                publisherInput.value = data.company_name;
                                foundPublisher = true;
                            }
                        }
                    });

                    // Set to 'Not Found' if no developer or publisher was found
                    if (!foundDeveloper) {
                        document.querySelector('#developer').value = 'Not Found';
                    }
                    if (!foundPublisher) {
                        document.querySelector('#publisher').value = 'Not Found';
                    }
                })
                .catch(error => console.error('Error processing company roles:', error));
        } else {
            // If no involved companies, set developer and publisher to 'Not Found'
            document.querySelector('#developer').value = 'Not Found';
            document.querySelector('#publisher').value = 'Not Found';
        }

        // Update for video URLs
        const videoURLsInput = document.querySelector('#video_urls');
        if (gameData.videos && gameData.videos.length > 0) {
            // Form the YouTube URLs and join them with commas, ensuring they start with https://
            const videoURLs = gameData.videos.map(video => {
                // Check if video.url is defined to avoid TypeError
                if (video.url) {
                    let url = video.url;
                    if (!url.startsWith('http://') && !url.startsWith('https://')) {
                        url = 'https://' + url; // Prepend https:// if no scheme is present
                    }
                    return url;
                }
                return ''; // Return an empty string or a placeholder URL if video.url is undefined
            }).filter(url => url !== '').join(','); // Filter out any empty strings to avoid invalid URLs in the list
            videoURLsInput.value = videoURLs; // Populate the input field with corrected YouTube URLs
        } else {
            videoURLsInput.value = ''; // Clear the field if there are no videos
        }
    }

    function checkFieldsAndToggleSubmit() {
        const igdbIdIsValid = igdbIdInput.value.trim().length > 0 && /^\d+$/.test(igdbIdInput.value);
        const fullPathIsValid = fullPathInput.value.trim().length > 0;
        const nameIsValid = nameInput.value.trim().length > 0;

        validateField(igdbIdInput, igdbIdIsValid);
        validateField(fullPathInput, fullPathIsValid);
        validateField(nameInput, nameIsValid);

        updateButtonState(!(igdbIdIsValid && fullPathIsValid && nameIsValid));
    }

    function showFeedback(element, message, isSuccess) {
        element.textContent = message;
        element.className = isSuccess ? 'form-text text-success' : 'form-text text-danger';
    }
    function triggerClickOnEnter(event, button) {
        if (event.keyCode === 13) {
            event.preventDefault();
            button.click();
        }
    }
    
    igdbIdInput.addEventListener('keypress', function(event) {
        triggerClickOnEnter(event, document.querySelector('#search-igdb-btn'));
    });

    nameInput.addEventListener('keypress', function(event) {
        triggerClickOnEnter(event, document.querySelector('#search-igdb'));
    });

    igdbIdSearchButton.addEventListener('click', function() {
        const igdbId = igdbIdInput.value;
        if (igdbId) {
            setSearchLoading(igdbIdSearchButton, igdbIdSearchStatus, true, 'Looking up game…');
            fetch(`/api/search_igdb_by_id?igdb_id=${igdbId}`)
                .then(response => response.json())
                .then(data => {
                    console.log("API Response (IGDB id Search):", data);
                    
                    if (data.error) {
                        console.error('Error:', data.error);
                        $.notify("Game not found", {
                            className: 'error',
                            position: 'top center'
                        });
                        igdbIdSearchStatus.textContent = 'No game was found for that IGDB ID.';
                    } else {
                        const gameDetailsCollapse = document.querySelector('#gameDetails');
                        if (gameDetailsCollapse) {
                            const bootstrapCollapse = new bootstrap.Collapse(gameDetailsCollapse, {
                                show: true
                            });
                        }
                        
                        setTimeout(() => {
                            // Update form fields
                            nameInput.value = data.name;
                            document.querySelector('#summary').value = data.summary || '';
                            document.querySelector('#storyline').value = data.storyline || '';
                    const instInput1 = document.querySelector('#install_instructions'); if (instInput1) instInput1.value = data.install_instructions || '';
                            urlInput.value = data.url || '';
                            document.querySelector('#video_urls').value = data.video_urls || '';
                            
                            checkFieldsAndToggleSubmit();
                            igdbIdSearchStatus.textContent = 'Game details loaded.';
                        }, 300);
                    }
                })
                .catch(error => {
                    console.error('Error:', error);
                    igdbIdSearchStatus.textContent = 'Unable to look up that IGDB ID. Please try again.';
                })
                .finally(() => setSearchLoading(igdbIdSearchButton, igdbIdSearchStatus, false));
        } else {
            igdbIdSearchStatus.textContent = 'Enter an IGDB ID to look up a game.';
        }
    });

    igdbNameSearchButton.addEventListener('click', function() {
        const gameName = nameInput.value;
        const platformId = document.querySelector('#platform_id').textContent; // Retrieve the platform ID from the HTML

        console.log(`Initiating IGDB search for name: ${gameName}`);
        if (gameName) {
            setSearchLoading(igdbNameSearchButton, igdbNameSearchStatus, true, 'Searching IGDB…');
            fetch(`/api/search_igdb_by_name?name=${encodeURIComponent(gameName)}&platform_id=${encodeURIComponent(platformId)}`)
                .then(response => response.json())
                .then(data => {
                    console.log("API Response (IGDB name Search):", data);
                    const resultsContainer = document.querySelector('#search-results');
                    resultsContainer.innerHTML = '';
                    if (data.results && data.results.length > 0) {
                        data.results.forEach(game => {
                            const resultItem = document.createElement('div');
                            resultItem.className = 'search-result-item';
                            
                            // Initialize the img element early to ensure order
                            const img = document.createElement('img');
                            img.alt = 'Cover Image';
                            img.style.width = '50px'; // Adjust size as needed
                            img.style.height = 'auto';
                            img.style.marginRight = '10px'; // Spacing between image and text
    
                            // Fetch the cover thumbnail URL
                            fetch(`/api/get_cover_thumbnail?igdb_id=${game.id}`)
                            .then(response => response.json())
                            .then(coverData => {
                                if (!coverData.error && coverData.cover_url) {
                                    img.src = coverData.cover_url;
                                } else {
                                    // Use a fallback image if cover URL not found
                                    img.src = '/static/newstyle/nocoverfound.png';
                                }
                                // Prepend the img element regardless of fetch outcome
                                resultItem.prepend(img);
                            })
                            .catch(error => {
                                console.error('Error fetching cover thumbnail:', error);
                                img.src = '/static/newstyle/nocoverfound.png'; // Fallback if fetch fails
                                resultItem.prepend(img);
                            });
                            
                            // Append game name text
                            const textNode = document.createTextNode(game.name);
                            resultItem.appendChild(textNode);
    
                            resultItem.addEventListener('click', function() {
                                // Update form with game data upon selection
                                updateFormWithGameData(game);
    
                                // Ensure the collapsible section is expanded
                                const gameDetailsCollapse = document.querySelector('#gameDetails');
                                if (gameDetailsCollapse) {
                                    const bootstrapCollapse = new bootstrap.Collapse(gameDetailsCollapse, {
                                        show: true
                                    });
                                }
                                
                                // Update essential fields
                                igdbIdInput.value = game.id;
                                nameInput.value = game.name;
                                document.querySelector('#summary').value = game.summary || '';
                                document.querySelector('#storyline').value = game.storyline || '';
                         const instInput2 = document.querySelector('#install_instructions'); if (instInput2) instInput2.value = game.install_instructions || '';
                                document.querySelector('#url').value = game.url || '';
                                checkFieldsAndToggleSubmit();
                                resultsContainer.innerHTML = ''; // Clear results after selection
                            });
    
                            resultsContainer.appendChild(resultItem);
                        });
                    } else {
                        resultsContainer.textContent = 'No results found';
                    }
                    igdbNameSearchStatus.textContent = data.results && data.results.length > 0
                        ? `${data.results.length} result${data.results.length === 1 ? '' : 's'} found. Choose a game to fill in the form.`
                        : 'No matching games found.';
                })
                .catch(error => {
                    console.error('Error:', error);
                    igdbNameSearchStatus.textContent = 'Unable to search IGDB. Please try again.';
                })
                .finally(() => setSearchLoading(igdbNameSearchButton, igdbNameSearchStatus, false));
        } else {
            igdbNameSearchStatus.textContent = 'Enter a game name to search IGDB.';
        }
    });
    
    igdbIdInput.addEventListener('input', function() {
        this.value = this.value.replace(/\D/g, '');
        checkFieldsAndToggleSubmit();
    });

    fullPathInput.addEventListener('input', checkFieldsAndToggleSubmit);
    nameInput.addEventListener('input', checkFieldsAndToggleSubmit);

    igdbIdInput.addEventListener('blur', function() {
        const igdbId = this.value.trim();
        if (igdbId.length > 0) {
            // Skip validation for custom IDs
            if (parseInt(igdbId) >= 2000000420) {
                showFeedback(igdbIdFeedback, 'Custom game ID', true);
                return;
            }
            fetch(`/api/check_igdb_id?igdb_id=${igdbId}`)
                .then(response => response.json())
                .then(data => {
                    const isValid = data.available;
                    showFeedback(igdbIdFeedback, isValid ? 'IGDB ID is available' : 'IGDB ID is already in the database', isValid);
                    validateField(this, isValid);
                    checkFieldsAndToggleSubmit();
                })
                .catch(error => {
                    console.error('Error:', error);
                    showFeedback(igdbIdFeedback, 'Error checking IGDB ID', false);
                });
        }
    });

    fullPathInput.addEventListener('blur', function() {
        const fullPath = this.value;
        if (fullPath.trim().length > 0) {
            fetch(`/api/check_path_availability?full_disk_path=${encodeURIComponent(fullPath)}`)
                .then(response => response.json())
                .then(data => {
                    const isValid = data.available;
                    showFeedback(fullPathFeedback, isValid ? 'Path is accessible' : 'Path is not accessible', isValid);
                    validateField(this, isValid);
                    checkFieldsAndToggleSubmit();
                })
                .catch(error => {
                    console.error('Error:', error);
                    showFeedback(fullPathFeedback, 'Error checking path accessibility', false);
                });
        }
    });

    checkFieldsAndToggleSubmit();
    console.log("Ready to add a game!.");

    // Show spinner on form submit — detect which button triggered it
    const gameEditForm = document.querySelector('.game_edit-form');
    const allSubmitButtons = document.querySelectorAll('.game_edit-form button[type="submit"]');
    let lastClickedSubmit = null;

    allSubmitButtons.forEach(function(btn) {
        btn.addEventListener('click', function() {
            lastClickedSubmit = btn;
        });
    });

    if (gameEditForm) {
        gameEditForm.addEventListener('submit', function(event) {
            if (submitButton.disabled) return; // form is blocked (validation)

            // Disabled submit buttons are omitted from the browser payload. Preserve
            // the clicked action before disabling the controls so the backend can
            // distinguish a normal save from Save & Refresh Metadata.
            const submittedButton = event.submitter || lastClickedSubmit;
            if (submittedButton && submittedButton.name === 'action') {
                let actionInput = gameEditForm.querySelector('input[data-submitted-action]');
                if (!actionInput) {
                    actionInput = document.createElement('input');
                    actionInput.type = 'hidden';
                    actionInput.name = 'action';
                    actionInput.dataset.submittedAction = 'true';
                    gameEditForm.appendChild(actionInput);
                }
                actionInput.value = submittedButton.value;
            }

            const spinner = document.getElementById('saveSpinner');
            const spinnerMsg = document.getElementById('spinnerMessage');

            if (spinner) {
                const isRefresh = submittedButton && submittedButton.value === 'save_and_refresh';
                if (spinnerMsg) {
                    spinnerMsg.textContent = isRefresh
                        ? 'Saving and refreshing metadata\u2026'
                        : 'Saving game\u2026';
                }
                spinner.style.display = 'flex';
            }

            // Disable all submit buttons to prevent double-submit
            allSubmitButtons.forEach(function(btn) { btn.disabled = true; });
        });
    }
});
