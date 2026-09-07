from pathlib import Path


THEME = Path("sharewarez/setup/default_theme")


def test_shared_ui_primitives_cover_feedback_status_and_motion():
    base = (THEME / "css/base.css").read_text(encoding="utf-8")
    components = (THEME / "css/components.css").read_text(encoding="utf-8")

    assert "--status-active-color:" in base
    assert "--status-success-color:" in base
    assert "--status-warning-color:" in base
    assert "--status-danger-color:" in base
    assert ".app-empty-state" in components
    assert ".app-skeleton" in components
    assert ".ui-status" in components
    assert "@media (prefers-reduced-motion: no-preference)" in components
    assert "@keyframes appPageEnter" in components


def test_discover_keeps_secondary_moods_collapsed_and_card_metadata_compact():
    template = (Path("sharewarez/templates/games/discover.html")).read_text(encoding="utf-8")
    css = (THEME / "css/games/discover.css").read_text(encoding="utf-8")

    assert '<details class="home-quick-discover">' in template
    assert "Quick collection shortcuts" in template
    assert "{{ game.size }}" not in template
    assert "home-game-genres" not in template
    assert "home-personal-grid{% if personalized_games and (recent_downloads or recent_requests) %} has-activity" in template
    assert ".home-personal-grid.has-activity" in css


def test_library_exposes_sort_before_advanced_filters_and_hides_card_file_size():
    filters = Path("sharewarez/templates/games/library_filters.html").read_text(encoding="utf-8")
    template = Path("sharewarez/templates/games/library_browser.html").read_text(encoding="utf-8")
    javascript = (THEME / "js/library_pagination.js").read_text(encoding="utf-8")

    assert filters.index("library-filter-toolbar") < filters.index("libraryFiltersBody")
    assert filters.index('id="sortSelect"') < filters.index("libraryFiltersBody")
    assert 'aria-busy="false"' in template
    assert "library-game-size" not in template
    assert "library-game-size" not in javascript
    assert "app-skeleton game-card-skeleton-cover" in javascript


def test_play_status_uses_semantic_classes_in_static_and_dynamic_cards():
    library_template = Path("sharewarez/templates/games/library_cards.html").read_text(encoding="utf-8")
    details_template = Path("sharewarez/templates/games/game_details.html").read_text(encoding="utf-8")
    pagination = (THEME / "js/library_pagination.js").read_text(encoding="utf-8")
    manager = (THEME / "js/game_status_manager.js").read_text(encoding="utf-8")
    status_css = (THEME / "css/games/game_status.css").read_text(encoding="utf-8")

    for source in (library_template, details_template, pagination, manager):
        assert "#4A90E2" not in source
        assert "#50C878" not in source
        assert "#FFD700" not in source
    assert "status-icon-unfinished" in library_template
    assert "status-icon-unfinished" in details_template
    assert "response.html" in pagination
    assert "library_cards.html" in Path("sharewarez/routes.py").read_text(encoding="utf-8")
    assert "`status-icon-${status || 'empty'}`" in manager
    assert "color: var(--status-success-color)" in status_css


def test_game_action_menu_rows_and_close_behavior_are_shared():
    base = (THEME / "css/base.css").read_text(encoding="utf-8")
    template = Path("sharewarez/templates/games/popup_menu.html").read_text(encoding="utf-8")
    javascript = (THEME / "js/popup_menu.js").read_text(encoding="utf-8")

    assert ".popup-menu .menu-button" in base
    assert "min-height: 44px" in base
    assert "menu-button menu-button-danger delete-game" in template
    assert 'class="menu-button">Open IGDB Page</a>' in template
    assert "function closeMenu(menu, options = {})" in javascript
    assert "menu?.closest('.game-card') || menu?.closest('.game-card-coverimage')" in javascript
    assert "closeMenu(menu, { restoreFocus: true })" in javascript
    assert "style.backgroundColor" not in javascript


def test_game_details_mobile_favorite_uses_shared_state_contract():
    template = Path("sharewarez/templates/games/game_details.html").read_text(encoding="utf-8")
    manager = (THEME / "js/favorites_manager.js").read_text(encoding="utf-8")

    assert 'class="favorite-btn favorite-btn-mobile"' in template
    assert "favorite-btn-cover')?.click()" not in template
    assert "const setPendingAppearance" in manager
    assert "label.textContent = isFavorite ? 'Favorited' : 'Favorite'" in manager


def test_narrow_library_views_reserve_non_overlapping_action_space():
    css = (THEME / "css/games/library_browser.css").read_text(encoding="utf-8")

    assert "grid-template-columns: 104px minmax(0, 1fr)" in css
    assert "@media (max-width: 379px)" in css
    assert "grid-template-columns: repeat(2, minmax(0, 1fr)) !important" in css


def test_game_editor_uses_task_sections_and_safe_action_contract():
    template = Path("sharewarez/templates/admin/admin_game_identify.html").read_text(encoding="utf-8")
    css = (THEME / "css/admin/admin_game_identify.css").read_text(encoding="utf-8")
    javascript = (THEME / "js/admin_game_identify.js").read_text(encoding="utf-8")
    route = Path("sharewarez/routes_games_ext/edit.py").read_text(encoding="utf-8")

    for heading in ("Overview", "Package &amp; installation", "Classification", "Links &amp; media"):
        assert heading in template
    assert 'class="game-edit-identification"' in template
    assert template.count("{{ actions(") == 2
    assert "gameDetails" not in template
    assert ".game-identify-page .form-group > label" in css
    assert "\nlabel {" not in css
    assert "const submitButtons = Array.from" in javascript
    assert "event.preventDefault();" in javascript
    assert "function updateSelectionCounts()" in javascript
    assert "def render_editor():" in route
    assert "return redirect(url_for('games.game_details', game_uuid=game_uuid))" in route


def test_scan_workspace_flattens_active_tab_panel():
    css = (THEME / "css/admin/admin_manage_scanjobs.css").read_text(encoding="utf-8")

    assert "#content .scan-management-page .admin_manage_scanjobs-tab-content :is(" in css
    assert "backdrop-filter: none;" in css


def test_operations_pages_use_compact_theme_aware_components():
    jobs_template = Path("sharewarez/templates/admin/admin_background_jobs.html").read_text(encoding="utf-8")
    jobs_js = (THEME / "js/admin_background_jobs.js").read_text(encoding="utf-8")
    server_template = Path("sharewarez/templates/admin/new_server_info.html").read_text(encoding="utf-8")
    statistics_template = Path("sharewarez/templates/admin/admin_statistics.html").read_text(encoding="utf-8")

    assert "apis.background_jobs" in jobs_template
    assert "response.json()" in jobs_js
    assert "setInterval(refreshJobs, 8000)" in jobs_js
    assert "Chart.js" not in server_template
    assert "resource-track" in server_template
    assert 'id="downloadsPerUserChart"' not in statistics_template
    assert statistics_template.count("<canvas") == 5


def test_operations_alignment_and_notification_badge_contracts():
    base_template = Path("sharewarez/templates/base.html").read_text(encoding="utf-8")
    logs_template = Path("sharewarez/templates/admin/admin_server_logs.html").read_text(encoding="utf-8")
    logs_css = (THEME / "css/admin/admin_system_logs.css").read_text(encoding="utf-8")
    jobs_css = (THEME / "css/admin/admin_background_jobs.css").read_text(encoding="utf-8")

    activity_links = [
        line for line in base_template.splitlines()
        if "url_for('site.activity')" in line
    ]
    assert activity_links
    assert all("unread_notification_count" not in line for line in activity_links)
    assert 'class="btn btn-danger" id="clearLogsBtn"' in logs_template
    assert "width: min(1440px, calc(100% - 2rem))" in logs_css
    assert "width: min(1440px, calc(100% - 2rem))" in jobs_css


def test_background_job_actions_are_aligned_and_bulk_delete_form_is_valid():
    jobs_template = Path("sharewarez/templates/admin/admin_background_jobs.html").read_text(encoding="utf-8")
    jobs_css = (THEME / "css/admin/admin_background_jobs.css").read_text(encoding="utf-8")

    filter_form_end = jobs_template.index("</form>", jobs_template.index('class="job-filters"'))
    bulk_form_start = jobs_template.index('class="job-bulk-actions"')
    assert bulk_form_start > filter_form_end
    assert 'action="{{ url_for(\'admin2.clear_failed_background_jobs\') }}"' in jobs_template
    assert 'Clear {{ counts.get(\'failed\', 0) }} failed job' in jobs_template
    assert 'btn btn-secondary btn-sm' not in jobs_template
    assert ".job-actions .btn" in jobs_css
    assert "width: 5.5rem" in jobs_css
    assert "height: 2.5rem" in jobs_css


def test_scan_restart_worker_does_not_reuse_request_context():
    routes = Path("sharewarez/routes.py").read_text(encoding="utf-8")
    restart_route = routes[routes.index("def restart_scan_job"):routes.index("@bp.route('/edit_game_images")]

    assert "app = current_app._get_current_object()" in restart_route
    assert "with app.app_context():" in restart_route
    assert "worker_job = db.session.get(ScanJob, job_id)" in restart_route
    assert "@copy_current_request_context" not in restart_route


def test_active_download_progress_uses_scoped_bar_styles_and_labels():
    template = Path("sharewarez/templates/admin/admin_manage_downloads.html").read_text(encoding="utf-8")
    javascript = (THEME / "js/admin_transfer_live.js").read_text(encoding="utf-8")
    css = (THEME / "css/admin/admin_manage_downloads.css").read_text(encoding="utf-8")

    assert "admin_transfer_live.js" in template
    assert "active-transfer-progress-label" in javascript
    assert "expected_bytes_label" in javascript
    assert "active-transfer-details" in javascript
    assert ".active-transfer-details > span" in css
    assert ".active-transfer-item div > span" not in css


def test_download_delivery_ui_explains_records_and_exposes_admin_controls():
    template = Path("sharewarez/templates/admin/admin_manage_downloads.html").read_text(encoding="utf-8")

    assert "One row per HTTP delivery" in template
    assert "Reusable access" in template
    assert "Queue priority applies only while waiting for a transfer slot" in template
    assert "download.cancel_transfer" in template
    assert "download.clear_transfer_history" in template
    assert "transfer.game or" in template


def test_pwa_assets_are_versioned_and_code_uses_network_first_updates():
    base_template = Path("sharewarez/templates/base.html").read_text(encoding="utf-8")
    service_worker = Path("sharewarez/templates/pwa/service-worker.js").read_text(encoding="utf-8")

    assert "'js/pwa.js'|static_asset" in base_template
    assert "versionedCode" in service_worker
    assert "const update = fetch(request)" in service_worker
    assert "if (versionedCode)" in service_worker


def test_final_page_shell_audit_uses_shared_headers_and_main_landmarks():
    library_editor = Path("sharewarez/templates/admin/admin_manage_library_create.html").read_text(encoding="utf-8")
    collections = Path("sharewarez/templates/admin/admin_manage_collections.html").read_text(encoding="utf-8")
    collection_editor = Path("sharewarez/templates/admin/admin_collection_editor.html").read_text(encoding="utf-8")
    admin_downloads = Path("sharewarez/templates/admin/admin_manage_downloads.html").read_text(encoding="utf-8")
    member_downloads = Path("sharewarez/templates/games/manage_downloads.html").read_text(encoding="utf-8")
    scan_management = Path("sharewarez/templates/admin/admin_manage_scanjobs.html").read_text(encoding="utf-8")
    request_detail = Path("sharewarez/templates/admin/admin_game_request_details.html").read_text(encoding="utf-8")
    issue_detail = Path("sharewarez/templates/admin/admin_issue_detail.html").read_text(encoding="utf-8")

    assert '<main class="app-page app-page--narrow library-editor-page">' in library_editor
    assert '<h1>{{ page_title }}</h1>' in library_editor
    assert "page_vendor_assets" in library_editor
    assert 'class="app-surface collections-admin-card card"' not in collections
    assert 'class="app-surface collection-editor-card card"' not in collection_editor
    assert '<main class="app-page downloads-page"' in admin_downloads
    assert '<main class="app-page downloads-page"' in member_downloads
    assert '<main class="app-page scan-management-page">' in scan_management
    assert 'aria_label=manual_form.folder_path.label.text' in scan_management
    assert 'class="app-page-header request-detail-hero request-panel"' in request_detail
    assert 'class="app-page-header app-surface issue-detail-header"' in issue_detail
    assert "style=" not in request_detail
    assert "style=" not in issue_detail


def test_final_theme_and_vendor_audit_removes_legacy_leaks():
    base_template = Path("sharewarez/templates/base.html").read_text(encoding="utf-8")
    admin_downloads = Path("sharewarez/templates/admin/admin_manage_downloads.html").read_text(encoding="utf-8")
    newsletter = Path("sharewarez/templates/admin/admin_newsletter.html").read_text(encoding="utf-8")
    requests_css = (THEME / "css/requests.css").read_text(encoding="utf-8")
    issues_css = (THEME / "css/issues.css").read_text(encoding="utf-8")
    game_details_css = (THEME / "css/games/game_details.css").read_text(encoding="utf-8")

    assert "cdn.datatables.net" not in base_template
    assert "cropperjs/1.6.1" not in base_template
    assert "notify/0.4.2" not in base_template
    assert "cdn.datatables.net" not in admin_downloads
    assert admin_downloads.count("Apply filters") == 1
    assert "Zip File Path" not in admin_downloads
    assert "Completion Time" not in admin_downloads
    assert "cdn.ckeditor.com" in newsletter
    assert 'class="app-surface newsletter-compose-panel"' in newsletter
    assert 'class="app-surface newsletter-history"' in newsletter
    for stylesheet in (requests_css, issues_css, game_details_css):
        assert "#03b2f8" not in stylesheet
        assert "#4A90E2" not in stylesheet
    assert not Path("sharewarez/templates/admin/admin_server_status.html").exists()
    assert not (THEME / "js/admin_manage_scanjobs_backup.js").exists()
