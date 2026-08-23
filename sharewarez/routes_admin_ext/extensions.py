from flask import redirect, url_for
from flask_login import login_required
from sharewarez.utils.auth import admin_required
from . import admin2_bp

@admin2_bp.route('/admin/extensions')
@login_required
@admin_required
def extensions():
    return redirect(
        url_for('main.admin_scan_management', active_tab='file_extensions'),
        code=308,
    )
