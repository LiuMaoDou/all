#!/usr/bin/env python3
"""毛豆百脑汇 - SQLite REST API"""

import sqlite3
import json
import os
import uuid
from datetime import datetime
from flask import Flask, request, jsonify, g, send_from_directory

app = Flask(__name__)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'all_nav.db')
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(exc):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_nav_flat (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL DEFAULT '',
            name TEXT,
            logo TEXT DEFAULT '',
            description TEXT DEFAULT '',
            url TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    conn.close()

# --- REST API ---

@app.route('/api/ai_nav_flat', methods=['GET'])
def get_all():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM ai_nav_flat ORDER BY sort_order ASC, created_at ASC"
    ).fetchall()
    return jsonify([dict(r) for r in rows])

@app.route('/api/ai_nav_flat', methods=['POST'])
def insert():
    data = request.get_json()
    if not data or not isinstance(data, list):
        data = [data] if data else []
    
    db = get_db()
    results = []
    for item in data:
        cur = db.execute(
            """INSERT INTO ai_nav_flat (category, name, logo, description, url, sort_order)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                item.get('category', ''),
                item.get('name'),
                item.get('logo', ''),
                item.get('description', ''),
                item.get('url', ''),
                item.get('sort_order', 0)
            )
        )
        results.append({'id': cur.lastrowid})
    db.commit()
    return jsonify(results), 201

@app.route('/api/ai_nav_flat', methods=['PATCH'])
def update():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data to update'}), 400
    # Support Supabase-style query params: ?eq_column=value
    eq_filters = {}
    for key in request.args:
        if key.startswith('eq_'):
            col = key[3:]
            eq_filters[col] = request.args.get(key)
    
    if not eq_filters:
        return jsonify({'error': 'No filter specified'}), 400
    
    db = get_db()
    # 验证列名存在，防止SQL注入
    cursor = db.execute("PRAGMA table_info(ai_nav_flat)")
    valid_cols = {row[1] for row in cursor.fetchall()}
    for col in list(eq_filters.keys()) + list(data.keys()):
        if col not in valid_cols:
            return jsonify({'error': f'Invalid column: {col}'}), 400
    
    if not data:
        return jsonify({'error': 'No data to update'}), 400
    
    eq_info = data.pop('_eq', {})
    eq_filters.update(eq_info)
    
    db = get_db()
    # 验证列名存在，防止SQL注入
    cursor = db.execute("PRAGMA table_info(ai_nav_flat)")
    valid_cols = {row[1] for row in cursor.fetchall()}
    for col in list(eq_filters.keys()) + list(data.keys()):
        if col not in valid_cols:
            return jsonify({'error': f'Invalid column: {col}'}), 400
    
    set_clause = ', '.join(f"{k} = ?" for k in data.keys())
    values = list(data.values())
    
    where_parts = []
    where_values = []
    for col, val in eq_filters.items():
        where_parts.append(f"{col} = ?")
        where_values.append(val)
    
    if not where_parts:
        return jsonify({'error': 'No filter specified'}), 400
    
    where_clause = ' AND '.join(where_parts)
    sql = f"UPDATE ai_nav_flat SET {set_clause} WHERE {where_clause}"
    
    cur = db.execute(sql, values + where_values)
    db.commit()
    
    return jsonify({'updated': cur.rowcount})

@app.route('/api/ai_nav_flat', methods=['DELETE'])
def delete():
    # Support Supabase-style query params: ?eq_column=value
    eq_filters = {}
    for key in request.args:
        if key.startswith('eq_'):
            col = key[3:]
            eq_filters[col] = request.args.get(key)
    
    if not eq_filters:
        return jsonify({'error': 'No filter specified'}), 400
    
    db = get_db()
    # 验证列名存在，防止SQL注入
    cursor = db.execute("PRAGMA table_info(ai_nav_flat)")
    valid_cols = {row[1] for row in cursor.fetchall()}
    for col in eq_filters:
        if col not in valid_cols:
            return jsonify({'error': f'Invalid column: {col}'}), 400
    
    db = get_db()
    
    where_parts = []
    where_values = []
    for col, val in eq_filters.items():
        where_parts.append(f"{col} = ?")
        where_values.append(val)
    
    where_clause = ' AND '.join(where_parts)
    sql = f"DELETE FROM ai_nav_flat WHERE {where_clause}"
    
    cur = db.execute(sql, where_values)
    db.commit()
    
    return jsonify({'deleted': cur.rowcount})

# --- 图片上传 ---

@app.route('/api/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    f = request.files['file']
    if f.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    # 生成安全文件名
    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico'):
        return jsonify({'error': 'Unsupported file type'}), 400
    safe_name = f"{uuid.uuid4().hex}{ext}"
    f.save(os.path.join(UPLOAD_DIR, safe_name))

    return jsonify({'url': f'/uploads/{safe_name}'}), 201


if __name__ == '__main__':
    init_db()
    app.run(host='127.0.0.1', port=5231)
