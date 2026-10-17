#!/usr/bin/env python3
"""毛豆百脑汇: a same-origin Flask application backed by SQLite."""

import io
import json
import os
import secrets
import sqlite3
import uuid
import warnings
from pathlib import Path
from urllib.parse import urlsplit
from xml.etree import ElementTree

from flask import Flask, current_app, g, jsonify, request, send_from_directory
from PIL import Image, UnidentifiedImageError
from werkzeug.exceptions import BadRequest, Conflict, HTTPException, NotFound

ROOT = Path(__file__).resolve().parent
CATEGORY_ICONS = tuple(name for name in json.loads((ROOT / 'assets/lucide/icons.json').read_text())
                       if name != 'layout-grid')
FIELDS = {'category', 'name', 'logo', 'description', 'url', 'sort_order'}
LIMITS = {'category': 120, 'name': 200, 'logo': 200_000, 'description': 10_000, 'url': 4096}
IMAGE_FORMATS = {'.png': 'PNG', '.jpg': 'JPEG', '.jpeg': 'JPEG', '.gif': 'GIF',
                 '.webp': 'WEBP', '.ico': 'ICO'}


def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(current_app.config['DATABASE'], timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys=ON')
    return g.db


def init_db():
    db = get_db()
    db.execute('PRAGMA journal_mode=WAL')
    # Serialize startup migrations, including when several WSGI workers start together.
    with db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE IF NOT EXISTS ai_nav_flat (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL DEFAULT '', name TEXT,
            logo TEXT DEFAULT '', description TEXT DEFAULT '', url TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )''')
        columns = {row['name'] for row in db.execute('PRAGMA table_info(ai_nav_flat)')}
        if 'category_sort_order' not in columns:
            names = dict.fromkeys(row['category'] for row in db.execute(
                'SELECT category FROM ai_nav_flat ORDER BY sort_order, created_at, id'))
            db.execute('ALTER TABLE ai_nav_flat ADD COLUMN category_sort_order INTEGER NOT NULL DEFAULT 0')
            db.executemany('UPDATE ai_nav_flat SET category_sort_order=? WHERE category=?',
                           [(order, name) for order, name in enumerate(names)])
        if 'category_icon' not in columns:
            db.execute("ALTER TABLE ai_nav_flat ADD COLUMN category_icon TEXT NOT NULL DEFAULT ''")
        # Fill legacy categories once. All tools in a category share its saved icon.
        missing_icons = db.execute("SELECT DISTINCT category FROM ai_nav_flat WHERE category_icon=''").fetchall()
        for row in missing_icons:
            db.execute('UPDATE ai_nav_flat SET category_icon=? WHERE category=?',
                       (category_icon(db, row['category']), row['category']))
        db.execute('''CREATE INDEX IF NOT EXISTS idx_nav_order ON ai_nav_flat
                      (category_sort_order, category, sort_order, created_at, id)''')
        db.execute('CREATE INDEX IF NOT EXISTS idx_nav_category ON ai_nav_flat(category)')


def validate_fields(data, *, partial=False):
    if not isinstance(data, dict) or not data:
        raise BadRequest('Expected a non-empty JSON object')
    if set(data) - FIELDS:
        raise BadRequest('Unknown or read-only fields: ' + ', '.join(sorted(set(data) - FIELDS)))
    if not partial and 'category' not in data:
        raise BadRequest('Category is required')
    cleaned = dict(data)
    for field, limit in LIMITS.items():
        if field not in cleaned:
            continue
        value = cleaned[field]
        if field == 'name' and value is None and not partial:
            continue
        if not isinstance(value, str):
            raise BadRequest(f'{field} must be a string')
        value = value.strip()
        if len(value) > limit or (field in ('category', 'name') and not value):
            raise BadRequest(f'Invalid {field} length (maximum {limit})')
        cleaned[field] = value
    if 'sort_order' in cleaned:
        value = cleaned['sort_order']
        if type(value) is not int or not 0 <= value <= 2_147_483_647:
            raise BadRequest('sort_order must be a non-negative integer')
    if cleaned.get('url'):
        try:
            url = urlsplit(cleaned['url'])
            valid = url.scheme in ('http', 'https') and bool(url.hostname)
        except ValueError:
            valid = False
        if not valid or any(ord(char) < 33 for char in cleaned['url']):
            raise BadRequest('URL must be an absolute http:// or https:// address')
    return cleaned


def filters():
    if not request.args or set(request.args) - {'eq_id', 'eq_category'}:
        raise BadRequest('Use eq_id or eq_category to select records')
    if any(len(values) != 1 for _, values in request.args.lists()):
        raise BadRequest('Duplicate filters are not supported')
    values = {key[3:]: value for key, value in request.args.items()}
    return ' AND '.join(f'{key}=?' for key in values), list(values.values())


def category_order(db, category):
    row = db.execute('SELECT MIN(category_sort_order) FROM ai_nav_flat WHERE category=?',
                     (category,)).fetchone()
    if row[0] is not None:
        return row[0]
    return db.execute('SELECT COALESCE(MAX(category_sort_order), -1) + 1 FROM ai_nav_flat').fetchone()[0]


def next_tool_order(db, category):
    return db.execute('''SELECT COALESCE(MAX(sort_order), -1) + 1 FROM ai_nav_flat
                         WHERE category=? AND name IS NOT NULL''', (category,)).fetchone()[0]


def category_icon(db, category):
    row = db.execute("SELECT category_icon FROM ai_nav_flat WHERE category=? AND category_icon!='' LIMIT 1",
                     (category,)).fetchone()
    if row:
        return row[0]
    used = {row[0] for row in db.execute('SELECT DISTINCT category_icon FROM ai_nav_flat')}
    return secrets.choice([icon for icon in CATEGORY_ICONS if icon not in used] or CATEGORY_ICONS)


def preserve_category(db, category, order, icon):
    """Keep an empty category after its last tool is deleted or moved."""
    if not db.execute('SELECT 1 FROM ai_nav_flat WHERE category=?', (category,)).fetchone():
        db.execute('''INSERT INTO ai_nav_flat (category, name, category_sort_order, category_icon)
                      VALUES (?, NULL, ?, ?)''', (category, order, icon))


def create_app(config=None):
    app = Flask(__name__, static_folder=None)
    app.config.from_mapping(
        DATABASE=os.environ.get('ALL_NAV_DB', str(ROOT / 'all_nav.db')),
        UPLOAD_FOLDER=os.environ.get('ALL_NAV_UPLOAD_DIR', str(ROOT / 'uploads')),
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,
    )
    if config:
        app.config.update(config)
    Path(app.config['UPLOAD_FOLDER']).mkdir(parents=True, exist_ok=True)

    @app.teardown_appcontext
    def close_db(_exc):
        db = g.pop('db', None)
        if db is not None:
            db.close()

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error=error.description), error.code

    @app.errorhandler(sqlite3.OperationalError)
    def database_error(error):
        app.logger.exception('Database operation failed')
        return jsonify(error='Database unavailable; please retry'), 503

    @app.after_request
    def response_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        if request.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        if request.path.startswith('/uploads/'):
            response.headers['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
        else:
            response.headers['Content-Security-Policy'] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; img-src 'self' https: http: data:; "
                "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
            )
        return response

    @app.get('/')
    @app.get('/index.html')
    def index():
        return send_from_directory(ROOT, 'index.html')

    @app.get('/app.js')
    def javascript():
        return send_from_directory(ROOT, 'app.js')

    @app.get('/theme.js')
    def theme_script():
        return send_from_directory(ROOT, 'theme.js')

    @app.get('/styles.css')
    def stylesheet():
        return send_from_directory(ROOT, 'styles.css')

    @app.get('/favicon.ico')
    def favicon():
        return send_from_directory(ROOT, 'favicon.ico')

    @app.get('/assets/<path:name>')
    def asset(name):
        return send_from_directory(ROOT / 'assets', name)

    @app.get('/uploads/<name>')
    def uploaded_file(name):
        return send_from_directory(app.config['UPLOAD_FOLDER'], name, max_age=31536000)

    @app.get('/api/ai_nav_flat')
    def get_all():
        rows = get_db().execute('''SELECT * FROM ai_nav_flat
            ORDER BY category_sort_order, category, sort_order, created_at, id''')
        return jsonify([dict(row) for row in rows])

    @app.post('/api/ai_nav_flat')
    def insert():
        data = request.get_json()
        items = data if isinstance(data, list) else [data]
        if not items or len(items) > 500:
            raise BadRequest('Provide between 1 and 500 records')
        items = [validate_fields(item) for item in items]
        db = get_db()
        results = []
        with db:
            db.execute('BEGIN IMMEDIATE')
            for item in items:
                category = item['category']
                if item.get('name') is None and db.execute(
                        'SELECT 1 FROM ai_nav_flat WHERE category=?', (category,)).fetchone():
                    raise Conflict('Category already exists')
                cursor = db.execute('''INSERT INTO ai_nav_flat
                    (category, name, logo, description, url, sort_order, category_sort_order, category_icon)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', (
                        category, item.get('name'), item.get('logo', ''), item.get('description', ''),
                        item.get('url', ''), item.get('sort_order', next_tool_order(db, category)),
                        category_order(db, category), category_icon(db, category)))
                results.append({'id': cursor.lastrowid})
        return jsonify(results), 201

    @app.patch('/api/ai_nav_flat')
    def update():
        fields = validate_fields(request.get_json(), partial=True)
        where, values = filters()
        rename = 'eq_category' in request.args and 'eq_id' not in request.args
        if rename and set(fields) != {'category'}:
            raise BadRequest('Category updates may only rename the category; use /api/reorder for ordering')
        db = get_db()
        with db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute(f'SELECT * FROM ai_nav_flat WHERE {where}', values).fetchall()
            if not rows:
                raise NotFound('Record no longer exists')
            if 'category' in fields:
                destination = fields['category']
                old = rows[0]['category']
                if destination != old:
                    exists = db.execute('SELECT 1 FROM ai_nav_flat WHERE category=?', (destination,)).fetchone()
                    if rename:
                        if exists:
                            raise Conflict('Category already exists')
                    else:
                        if not exists:
                            raise BadRequest('Destination category does not exist')
                        fields['category_sort_order'] = category_order(db, destination)
                        fields['category_icon'] = category_icon(db, destination)
                        fields['sort_order'] = next_tool_order(db, destination)
            assignments = ', '.join(f'{key}=?' for key in fields)
            cursor = db.execute(f'UPDATE ai_nav_flat SET {assignments} WHERE {where}',
                                list(fields.values()) + values)
            if not rename:
                for row in rows:
                    preserve_category(db, row['category'], row['category_sort_order'], row['category_icon'])
        return jsonify(updated=cursor.rowcount)

    @app.delete('/api/ai_nav_flat')
    def delete():
        where, values = filters()
        db = get_db()
        with db:
            db.execute('BEGIN IMMEDIATE')
            rows = db.execute(f'SELECT * FROM ai_nav_flat WHERE {where}', values).fetchall()
            if not rows:
                raise NotFound('Record no longer exists')
            cursor = db.execute(f'DELETE FROM ai_nav_flat WHERE {where}', values)
            if 'eq_id' in request.args:
                for row in rows:
                    preserve_category(db, row['category'], row['category_sort_order'], row['category_icon'])
        return jsonify(deleted=cursor.rowcount)

    @app.post('/api/reorder')
    def reorder():
        data = request.get_json()
        if not isinstance(data, dict) or data.get('kind') not in ('categories', 'tools'):
            raise BadRequest('kind must be categories or tools')
        order = data.get('order')
        expected_type = str if data['kind'] == 'categories' else int
        if not isinstance(order, list) or any(type(value) is not expected_type for value in order):
            raise BadRequest('Invalid order list')
        if len(set(order)) != len(order):
            raise BadRequest('Order list contains duplicates')
        db = get_db()
        with db:
            db.execute('BEGIN IMMEDIATE')
            if data['kind'] == 'categories':
                existing = {row[0] for row in db.execute('SELECT DISTINCT category FROM ai_nav_flat')}
                sql = 'UPDATE ai_nav_flat SET category_sort_order=? WHERE category=?'
            else:
                category = data.get('category')
                if not isinstance(category, str):
                    raise BadRequest('Category is required')
                existing = {row[0] for row in db.execute(
                    "SELECT id FROM ai_nav_flat WHERE category=? AND name IS NOT NULL AND name!=''", (category,))}
                sql = 'UPDATE ai_nav_flat SET sort_order=? WHERE id=?'
            if set(order) != existing:
                raise Conflict('Items have changed; reload before reordering')
            db.executemany(sql, enumerate(order))
        return jsonify(updated=len(order))

    @app.post('/api/upload')
    def upload_file():
        upload = request.files.get('file')
        if upload is None or not upload.filename:
            raise BadRequest('Choose an image file')
        ext = Path(upload.filename).suffix.lower()
        if ext not in IMAGE_FORMATS and ext != '.svg':
            raise BadRequest('Unsupported image type')
        content = upload.read()
        try:
            if ext == '.svg':
                if b'<!DOCTYPE' in content.upper() or b'<!ENTITY' in content.upper():
                    raise ValueError('SVG entities are not supported')
                root = ElementTree.fromstring(content)
                if root.tag not in ('svg', '{http://www.w3.org/2000/svg}svg'):
                    raise ValueError('Not an SVG image')
            else:
                with warnings.catch_warnings():
                    warnings.simplefilter('error', Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(content)) as picture:
                        if picture.format != IMAGE_FORMATS[ext] or picture.width * picture.height > 20_000_000:
                            raise ValueError('Invalid image format or dimensions')
                        picture.verify()
        except (ValueError, OSError, SyntaxError, ElementTree.ParseError, UnidentifiedImageError,
                Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise BadRequest('Invalid image file (maximum 20 megapixels)') from exc
        name = f'{uuid.uuid4().hex}{ext}'
        (Path(app.config['UPLOAD_FOLDER']) / name).write_bytes(content)
        return jsonify(url=f'/uploads/{name}'), 201

    with app.app_context():
        init_db()
    return app


app = create_app()

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.environ.get('PORT', '5231')))
