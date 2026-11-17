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
    const manualIdentityInput = document.querySelector('#manual_identity');
    const manualMetadataInput = document.querySelector('#metadata_manual_fields');
    document.querySelector('#metadata_tracking_active').value = '1';
    const editableMetadataFields = new Set(['name', 'summary', 'storyline', 'url', 'video_urls', 'first_release_date',
        'aggregated_rating', 'category', 'status', 'developer', 'publisher', 'genres', 'themes', 'game_modes', 'platforms', 'player_perspectives']);
    let manualMetadataFields;
    try { manualMetadataFields = new Set(JSON.parse(manualMetadataInput.value || '[]')); }
    catch (error) { manualMetadataFields = new Set(); }
    const fullPathInput = document.querySelector('#full_disk_path');
    const nameInput = document.querySelector('#name');
    const urlInput = document.querySelector('#url');
    const submitButtons = Array.from(document.querySelectorAll('.game_edit-form .game-save-action'));
    const submitButton = submitButtons[0];
    const libraryUuidInput = document.querySelector('#library_uuid');
    const igdbIdFeedback = document.querySelector('#igdb_id_feedback');
    const fullPathFeedback = document.createElement('small');
    const igdbIdSearchButton = document.querySelector('#search-igdb-btn');
    const igdbNameSearchButton = document.querySelector('#search-igdb');
    const igdbIdSearchStatus = document.querySelector('#igdb-id-search-status');
    const igdbNameSearchStatus = document.querySelector('#igdb-name-search-status');
    let formIsDirty = false;
    let formIsSubmitting = false;

    function allowIdentityReplacement() {
        return !formIsDirty || window.confirm('Replace the current form values with this game identity? Unsaved values may be overwritten.');
    }

    function focusField(field) {
        if (!field) return;
        for (let parent = field.parentElement; parent; parent = parent.parentElement) {
            if (parent.tagName === 'DETAILS') parent.open = true;
        }
        field.focus({ preventScroll: true });
        field.scrollIntoView({ block: 'center' });
    }

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

    // Add Non-Existing Game button handler
    document.querySelector('#add-non-existing-game').addEventListener('click', function() {
        if (!allowIdentityReplacement()) return;
        formIsDirty = true;
        // Keep lookup available so a custom entry can later be matched to IGDB.
        igdbIdInput.value = '';
        igdbIdInput.readOnly = false;
        manualIdentityInput.value = '1';
        showFeedback(igdbIdFeedback, 'A local identity will be created when you save.', true);

        // Clear and enable name field
        nameInput.value = '';
        nameInput.readOnly = false;
        nameInput.focus();

        document.querySelector('.game-edit-identification')?.setAttribute('open', '');
        checkFieldsAndToggleSubmit();
    });

    fullPathFeedback.id = 'full_disk_path_feedback';
    fullPathInput.parentNode.insertBefore(fullPathFeedback, fullPathInput.nextSibling);

    submitButtons.forEach(button => $(button).tooltip({
        title: "Complete the required fields first",
        placement: "top",
        trigger: "hover"
    }));

    function updateButtonState(isDisabled) {
        console.log(`Update submit button state: ${isDisabled ? 'Disabled' : 'Enabled'}`);
        submitButtons.forEach(button => {
            button.disabled = isDisabled;
            $(button).tooltip(isDisabled ? 'enable' : 'disable');
        });
    }

    function validateField(inputElement, isValid) {
        inputElement.setAttribute('aria-invalid', String(!isValid));
        if (isValid) {
            console.log(`${inputElement.id} is valid`);
            inputElement.classList.remove('invalid-input');
        } else {
            console.log(`${inputElement.id} is invalid`);
            inputElement.classList.add('invalid-input');
        }
    }

    function checkFieldsAndToggleSubmit() {
        const igdbIdIsValid = manualIdentityInput.value === '1' || (igdbIdInput.value.trim().length > 0 && /^\d+$/.test(igdbIdInput.value));
        const fullPathIsValid = document.getElementById('source_mode')?.value === 'torrent' || fullPathInput.value.trim().length > 0;
        const nameIsValid = nameInput.value.trim().length > 0;
        const libraryUuidIsValid = libraryUuidInput.value.trim().length > 0;

        validateField(igdbIdInput, igdbIdIsValid);
        validateField(fullPathInput, fullPathIsValid);
        validateField(nameInput, nameIsValid);
        validateField(libraryUuidInput, libraryUuidIsValid);

        const isValid = igdbIdIsValid && fullPathIsValid && nameIsValid && libraryUuidIsValid;
        updateButtonState(!isValid);
        return isValid;
    }

    function updateFormWithGameData(gameData) {
        const values = gameData.form_values;
        if (!values) throw new Error('Game identification returned incomplete form data. Please reload and try again.');
        for (const field of ['igdb_id', 'name', 'summary', 'storyline', 'url', 'video_urls',
                             'first_release_date', 'aggregated_rating', 'developer', 'publisher']) {
            const input = document.getElementById(field);
            if (input) input.value = values[field] ?? '';
        }
        for (const field of ['category', 'status']) {
            const input = document.getElementById(field);
            if (values[field] && [...input.options].some(option => option.value === values[field])) {
                input.value = values[field];
            }
        }
        for (const field of ['genres', 'game_modes', 'themes', 'platforms', 'player_perspectives']) {
            const selected = new Set((values[field] || []).map(value => value.trim().toLowerCase()));
            document.querySelectorAll(`#${field}-container input[type="checkbox"]`).forEach(input => {
                input.checked = selected.has(input.closest('label').textContent.trim().toLowerCase());
            });
        }
        updateSelectionCounts();
        manualMetadataFields.clear();
        manualMetadataInput.value = '[]';
        manualIdentityInput.value = '0';
        formIsDirty = true;
        checkFieldsAndToggleSubmit();
        focusField(nameInput);
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

    igdbIdSearchButton.addEventListener('click', async function() {
        const igdbId = igdbIdInput.value.trim();
        if (!igdbId) {
            igdbIdSearchStatus.textContent = 'Enter an IGDB ID to look up a game.';
            return;
        }
        setSearchLoading(igdbIdSearchButton, igdbIdSearchStatus, true, 'Looking up game…');
        try {
            const response = await fetch(`/api/search_igdb_by_id?igdb_id=${encodeURIComponent(igdbId)}`, {signal: AbortSignal.timeout(45000)});
            const data = await response.json();
            if (!response.ok || data.error) throw new Error(data.error || 'Unable to look up that IGDB ID.');
            if (!allowIdentityReplacement()) return;
            updateFormWithGameData(data);
            igdbIdSearchStatus.textContent = 'Game details loaded.';
        } catch (error) {
            igdbIdSearchStatus.textContent = error.name === 'TimeoutError' ? 'IGDB lookup timed out. Please try again.' : error.message;
        } finally {
            setSearchLoading(igdbIdSearchButton, igdbIdSearchStatus, false);
        }
    });

    igdbNameSearchButton.addEventListener('click', function() {
        const gameName = nameInput.value.trim();
        const platformId = document.querySelector('#platform_id').textContent; // Retrieve the platform ID from the HTML

        console.log(`Initiating IGDB search for name: ${gameName}`);
        if (gameName) {
            setSearchLoading(igdbNameSearchButton, igdbNameSearchStatus, true, 'Searching IGDB…');
            const searchParams = new URLSearchParams({name: gameName, platform_id: platformId, library_uuid: libraryUuidInput.value});
            fetch(`/api/search_igdb_by_name?${searchParams}`, {signal: AbortSignal.timeout(45000)})
                .then(async response => {
                    if (!response.ok) throw new Error('IGDB search is temporarily unavailable. Please try again.');
                    const data = await response.json();
                    if (data.error) throw new Error(data.error);
                    if (!Array.isArray(data.results)) throw new Error('IGDB returned an unexpected response. Please try again.');
                    return data;
                })
                .then(data => {
                    const resultsContainer = document.querySelector('#search-results');
                    resultsContainer.innerHTML = '';
                    if (data.results && data.results.length > 0) {
                        data.results.forEach(game => {
                            const resultItem = document.createElement('button');
                            resultItem.type = 'button';
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
                                if (!allowIdentityReplacement()) return;
                                formIsDirty = true;
                                manualIdentityInput.value = '0';
                                updateFormWithGameData(game);
                                resultsContainer.innerHTML = ''; // Clear results after selection
                                focusField(nameInput);
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
                    document.querySelector('#search-results').replaceChildren();
                    igdbNameSearchStatus.textContent = error.message || 'Unable to search IGDB. Please try again.';
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
    document.getElementById('source_mode')?.addEventListener('change', checkFieldsAndToggleSubmit);
    libraryUuidInput.addEventListener('change', checkFieldsAndToggleSubmit);
    nameInput.addEventListener('input', checkFieldsAndToggleSubmit);

    igdbIdInput.addEventListener('blur', function() {
        const igdbId = this.value.trim();
        if (igdbId.length > 0) {
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

    function updateSelectionCounts() {
        document.querySelectorAll('.metadata-multiselect-dropdown').forEach(dropdown => {
            const count = dropdown.querySelectorAll('input[type="checkbox"]:checked').length;
            const output = dropdown.querySelector('.metadata-selection-count');
            if (output) output.textContent = count ? `${count} selected` : 'None selected';
        });
    }

    document.querySelectorAll('.metadata-multiselect-dropdown input[type="checkbox"]').forEach(input => {
        input.addEventListener('change', updateSelectionCounts);
    });
    updateSelectionCounts();
    checkFieldsAndToggleSubmit();

    document.querySelectorAll('.field-error[id]').forEach(error => {
        const field = document.getElementById(error.id.replace(/-errors$/, ''));
        if (!field) return;
        field.setAttribute('aria-invalid', 'true');
        const descriptions = new Set((field.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean));
        descriptions.add(error.id);
        field.setAttribute('aria-describedby', [...descriptions].join(' '));
        for (let parent = field.parentElement; parent; parent = parent.parentElement) {
            if (parent.tagName === 'DETAILS') parent.open = true;
        }
    });

    const serverErrorLink = document.querySelector('.game-edit-error-summary a');
    if (serverErrorLink) {
        requestAnimationFrame(() => {
            const invalidField = document.querySelector(serverErrorLink.getAttribute('href'));
            invalidField?.setAttribute('aria-invalid', 'true');
            focusField(invalidField);
        });
    }

    // Show spinner on form submit — detect which button triggered it
    const gameEditForm = document.querySelector('.game_edit-form');
    const allSubmitButtons = document.querySelectorAll('.game_edit-form .game-save-action');
    let lastClickedSubmit = null;
    document.querySelectorAll('.game-edit-error-summary a').forEach(link => {
        link.addEventListener('click', event => {
            event.preventDefault();
            focusField(document.querySelector(link.getAttribute('href')));
        });
    });

    gameEditForm?.addEventListener('input', event => {
        formIsDirty = true;
        if (editableMetadataFields.has(event.target.name)) {
            manualMetadataFields.add(event.target.name);
            manualMetadataInput.value = JSON.stringify([...manualMetadataFields]);
        }
    });
    gameEditForm?.addEventListener('change', () => { formIsDirty = true; });
    document.querySelectorAll('.metadata-conflict-actions').forEach(form => {
        form.addEventListener('submit', event => {
            if (formIsDirty && !window.confirm('Resolve this conflict and discard your unsaved form changes?')) {
                event.preventDefault();
            }
        });
    });
    window.addEventListener('beforeunload', event => {
        if (!formIsDirty || formIsSubmitting) return;
        event.preventDefault();
        event.returnValue = '';
    });

    allSubmitButtons.forEach(function(btn) {
        btn.addEventListener('click', function() {
            lastClickedSubmit = btn;
        });
    });

    if (gameEditForm) {
        gameEditForm.addEventListener('submit', function(event) {
            if (formIsSubmitting) {
                event.preventDefault();
                return;
            }
            if (!checkFieldsAndToggleSubmit()) {
                event.preventDefault();
                focusField(document.querySelector('.game_edit-form .invalid-input'));
                return;
            }

            // Disabled submit buttons are omitted from the browser payload. Preserve
            // the clicked action before disabling the controls so the backend can
            // distinguish a normal save from Save & Refresh Metadata.
            const submittedButton = event.submitter || lastClickedSubmit || gameEditForm.querySelector('[value="save"]');
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

            if (document.getElementById('detach_local')?.checked &&
                !window.confirm('Remove this game’s association with its local files? The files stay on disk, but local downloads from this game will stop.')) {
                event.preventDefault();
                return;
            }
            formIsSubmitting = true;

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
            allSubmitButtons.forEach(function(btn) {
                btn.disabled = true;
                btn.setAttribute('aria-busy', 'true');
            });
        });
    }
});
