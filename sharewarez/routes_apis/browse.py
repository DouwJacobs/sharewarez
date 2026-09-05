# /sharewarez/routes_apis/browse.py
from flask import jsonify, request, current_app
import os
from flask_login import login_required
from sharewarez.utils.auth import admin_required
from . import apis_bp

@apis_bp.route('/browse_folders_ss')
@login_required
@admin_required
def browse_folders_ss():
    # Select base by operating system
    base_directory = current_app.config.get('BASE_FOLDER_WINDOWS') if os.name == 'nt' else current_app.config.get('BASE_FOLDER_POSIX')
    if not base_directory:
        return jsonify({'error': 'Scan location is not configured.'}), 404
    request_path = request.args.get('path', '')
    base_directory = os.path.realpath(base_directory)
    folder_path = os.path.realpath(os.path.join(base_directory, request_path))
    try:
        within_root = os.path.commonpath([base_directory, folder_path]) == base_directory
    except ValueError:
        within_root = False
    if not within_root:
        return jsonify({'error': 'Access denied'}), 403

    if not os.path.isdir(folder_path):
        return jsonify({
            'error': 'Scan location is unavailable.',
            'detail': f'The configured base directory does not exist: {base_directory}'
        }), 404

    try:
        # List directory contents; distinguish between files and directories.
        contents = [{'name': item,
                     'isDir': os.path.isdir(os.path.join(folder_path, item)),
                     'ext': os.path.splitext(item)[1][1:].lower() if not os.path.isdir(os.path.join(folder_path, item)) else None,
                     'size': os.path.getsize(os.path.join(folder_path, item)) if not os.path.isdir(os.path.join(folder_path, item)) else None
                     }
                    for item in sorted(os.listdir(folder_path))]
    except (OSError, PermissionError) as exc:
        current_app.logger.warning('Could not browse scan directory %s: %s', folder_path, exc)
        return jsonify({
            'error': 'Scan location could not be read.',
            'detail': 'Check that the storage mount is connected and readable by the application.'
        }), 403

    return jsonify({
        'items': sorted(contents, key=lambda x: (not x['isDir'], x['name'].lower())),
        'currentPath': request_path,
        'basePath': base_directory
    })
