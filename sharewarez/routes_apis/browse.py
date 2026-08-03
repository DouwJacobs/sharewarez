# /sharewarez/routes_apis/browse.py
from flask import jsonify, request, current_app
import os, sys
from flask_login import login_required
from sharewarez.utils.auth import admin_required
from . import apis_bp

@apis_bp.route('/browse_folders_ss')
@login_required
@admin_required
def browse_folders_ss():
    # Select base by operating system
    base_directory = current_app.config.get('BASE_FOLDER_WINDOWS') if os.name == 'nt' else current_app.config.get('BASE_FOLDER_POSIX')
    print(f'SS folder browser: Base directory: {base_directory}', file=sys.stderr)
    # Attempt to get 'path' from request arguments; default to an empty string which signifies the base directory
    request_path = request.args.get('path', '')
    print(f'SS folder browser: Requested path: {request_path}', file=sys.stderr)
    # Handle the default path case
    if not request_path:
        print(f'SS folder browser: No default path provided; using base directory: {base_directory}', file=sys.stderr)
        request_path = ''
        folder_path = base_directory
    else:
        # Safely construct the folder path to prevent directory traversal vulnerabilities
        folder_path = os.path.abspath(os.path.join(base_directory, request_path))
        print(f'SS folder browser: Folder path: {folder_path}', file=sys.stderr)
        # Prevent directory traversal outside the base directory
        if not folder_path.startswith(base_directory):
            print(f'SS folder browser: Access denied: {folder_path} outside of base directory: {base_directory}', file=sys.stderr)
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
