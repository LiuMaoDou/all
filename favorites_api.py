"""Persistent favorites and folders, independent of the tool directory."""

import secrets
from urllib.parse import urlsplit

from flask import jsonify, request
from werkzeug.exceptions import BadRequest, Conflict, NotFound


def init_favorites(db):
    db.execute('''CREATE TABLE IF NOT EXISTS favorite_folders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL COLLATE NOCASE UNIQUE,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS favorites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, url TEXT NOT NULL, icon TEXT NOT NULL,
        folder_id INTEGER REFERENCES favorite_folders(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    )''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_favorites_folder ON favorites(folder_id)')


def register_favorites(app, get_db, icons):
    def record(db, table, record_id):
        row = db.execute(f'SELECT * FROM {table} WHERE id=?', (record_id,)).fetchone()
        if row is None:
            raise NotFound('Record no longer exists')
        return dict(row)

    def text(value, field, maximum):
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
            raise BadRequest(f'{field} must contain between 1 and {maximum} characters')
        return value.strip()

    def payload(allowed):
        data = request.get_json()
        if not isinstance(data, dict) or not data or set(data) - allowed:
            raise BadRequest('Expected an object containing only editable fields')
        return data

    def folder_name():
        data = payload({'name'})
        name = text(data.get('name'), 'name', 120)
        if name in {'全部收藏', '未分类'}:
            raise BadRequest('This folder name is reserved')
        return name

    def bookmark_data(db, partial=False):
        data = payload({'name', 'url', 'folder_id'})
        if not partial and not {'name', 'url'} <= data.keys():
            raise BadRequest('name and url are required')
        clean = {}
        if 'name' in data:
            clean['name'] = text(data['name'], 'name', 200)
        if 'url' in data:
            url = text(data['url'], 'url', 4096)
            try:
                parsed = urlsplit(url)
                valid = parsed.scheme in {'http', 'https'} and bool(parsed.hostname)
            except ValueError:
                valid = False
            if not valid or any(ord(char) < 33 for char in url):
                raise BadRequest('URL must be an absolute http:// or https:// address')
            clean['url'] = url
        if 'folder_id' in data or not partial:
            folder_id = data.get('folder_id')
            if folder_id is not None:
                if type(folder_id) is not int or folder_id <= 0:
                    raise BadRequest('folder_id must be a positive integer or null')
                if not db.execute('SELECT 1 FROM favorite_folders WHERE id=?', (folder_id,)).fetchone():
                    raise BadRequest('Folder no longer exists')
            clean['folder_id'] = folder_id
        return clean

    @app.get('/api/favorites')
    def favorites_snapshot():
        db = get_db()
        return jsonify(
            folders=[dict(row) for row in db.execute('SELECT * FROM favorite_folders ORDER BY name, id')],
            bookmarks=[dict(row) for row in db.execute('SELECT * FROM favorites ORDER BY created_at, id')],
        )

    @app.post('/api/favorite-folders')
    def create_folder():
        name = folder_name()
        db = get_db()
        with db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM favorite_folders WHERE name=?', (name,)).fetchone():
                raise Conflict('Folder already exists')
            cursor = db.execute('INSERT INTO favorite_folders(name) VALUES (?)', (name,))
            result = record(db, 'favorite_folders', cursor.lastrowid)
        return jsonify(result), 201

    @app.patch('/api/favorite-folders/<int:folder_id>')
    def rename_folder(folder_id):
        name = folder_name()
        db = get_db()
        with db:
            db.execute('BEGIN IMMEDIATE')
            record(db, 'favorite_folders', folder_id)
            if db.execute('SELECT 1 FROM favorite_folders WHERE name=? AND id!=?', (name, folder_id)).fetchone():
                raise Conflict('Folder already exists')
            db.execute('UPDATE favorite_folders SET name=? WHERE id=?', (name, folder_id))
            result = record(db, 'favorite_folders', folder_id)
        return jsonify(result)

    @app.delete('/api/favorite-folders/<int:folder_id>')
    def delete_folder(folder_id):
        db = get_db()
        with db:
            db.execute('BEGIN IMMEDIATE')
            record(db, 'favorite_folders', folder_id)
            # ON DELETE SET NULL retains every bookmark in 未分类.
            db.execute('DELETE FROM favorite_folders WHERE id=?', (folder_id,))
        return jsonify(deleted=1)

    @app.post('/api/favorites')
    def create_bookmark():
        db = get_db()
        with db:
            db.execute('BEGIN IMMEDIATE')
            data = bookmark_data(db)
            used = {row[0] for row in db.execute('SELECT DISTINCT icon FROM favorites')}
            icon = secrets.choice([icon for icon in icons if icon not in used] or icons)
            cursor = db.execute('INSERT INTO favorites(name,url,folder_id,icon) VALUES (?,?,?,?)',
                                (data['name'], data['url'], data['folder_id'], icon))
            result = record(db, 'favorites', cursor.lastrowid)
        return jsonify(result), 201

    @app.patch('/api/favorites/<int:bookmark_id>')
    def update_bookmark(bookmark_id):
        db = get_db()
        with db:
            db.execute('BEGIN IMMEDIATE')
            record(db, 'favorites', bookmark_id)
            data = bookmark_data(db, partial=True)
            assignments = ', '.join(f'{field}=?' for field in data)
            db.execute(f'UPDATE favorites SET {assignments} WHERE id=?', [*data.values(), bookmark_id])
            result = record(db, 'favorites', bookmark_id)
        return jsonify(result)

    @app.delete('/api/favorites/<int:bookmark_id>')
    def delete_bookmark(bookmark_id):
        db = get_db()
        with db:
            db.execute('BEGIN IMMEDIATE')
            record(db, 'favorites', bookmark_id)
            db.execute('DELETE FROM favorites WHERE id=?', (bookmark_id,))
        return jsonify(deleted=1)
