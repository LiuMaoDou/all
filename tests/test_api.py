"""Regression tests use temporary databases and never touch application data."""
import io
import base64
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

# api:app is also a WSGI entry point; isolate its startup before importing it.
with tempfile.TemporaryDirectory() as bootstrap:
    with patch.dict(os.environ, {
        'ALL_NAV_DB': str(Path(bootstrap) / 'startup.db'),
        'ALL_NAV_UPLOAD_DIR': str(Path(bootstrap) / 'uploads'),
    }):
        from api import CATEGORY_ICONS, create_app


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = {
            'TESTING': True,
            'DATABASE': str(Path(self.directory.name) / 'test.db'),
            'UPLOAD_FOLDER': str(Path(self.directory.name) / 'uploads'),
        }
        self.app = create_app(self.config)
        self.client = self.app.test_client()

    def add(self, category='A', name='First', **fields):
        response = self.client.post('/api/ai_nav_flat', json=dict(category=category, name=name, **fields))
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()[0]['id']

    def rows(self):
        response = self.client.get('/api/ai_nav_flat')
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def test_app_and_assets_are_served_but_database_is_not(self):
        for path in ('/', '/index.html', '/app.js', '/theme.js', '/styles.css', '/favicon.ico',
                     '/assets/lucide/icons.json', '/assets/fonts/ubuntu.css', '/assets/fonts/ubuntu-400-latin.woff2'):
            with self.client.get(path) as response:
                self.assertEqual(response.status_code, 200, path)
                self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        for path in ('/all_nav.db', '/api.py', '/.env', '/uploads/../api.py', '/assets/../api.py'):
            self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.get('/api/ai_nav_flat').headers['Cache-Control'], 'no-store')

    def test_category_icons_are_assigned_once_and_persist_through_edits(self):
        with patch('api.secrets.choice', side_effect=lambda choices: choices[-1]) as choose:
            first = self.add('A', 'One')
            self.add('A', 'Two')
            second = self.add('B', 'Three')
            self.assertEqual(choose.call_count, 2)
        original = {row['category']: row['category_icon'] for row in self.rows()}
        self.assertEqual(len(set(original.values())), 2)
        self.assertTrue(set(original.values()) <= set(CATEGORY_ICONS))
        self.assertEqual(self.client.patch('/api/ai_nav_flat?eq_category=A', json={'category': 'Renamed'}).status_code, 200)
        self.assertEqual(self.client.post('/api/reorder', json={'kind': 'categories', 'order': ['B', 'Renamed']}).status_code, 200)
        self.assertEqual(self.client.patch(f'/api/ai_nav_flat?eq_id={first}', json={'category': 'B'}).status_code, 200)
        # Deleting B's last tool retains its empty category and original icon.
        self.assertEqual(self.client.patch(f'/api/ai_nav_flat?eq_id={second}', json={'category': 'Renamed'}).status_code, 200)
        self.assertEqual(self.client.delete(f'/api/ai_nav_flat?eq_id={first}').status_code, 200)
        expected = {'Renamed': original['A'], 'B': original['B']}
        for row in self.rows():
            self.assertEqual(row['category_icon'], expected[row['category']])
        before = self.rows()
        self.assertEqual(create_app(self.config).test_client().get('/api/ai_nav_flat').get_json(), before)

    def test_moving_last_tool_preserves_source_icon(self):
        tool = self.add('A', 'One')
        self.add('B', None)
        original = {row['category']: row['category_icon'] for row in self.rows()}
        self.assertEqual(self.client.patch(f'/api/ai_nav_flat?eq_id={tool}', json={'category': 'B'}).status_code, 200)
        rows = self.rows()
        self.assertTrue(any(row['category'] == 'A' and row['name'] is None for row in rows))
        for row in rows:
            self.assertEqual(row['category_icon'], original[row['category']])

    def test_category_icon_pool_can_be_reused_when_exhausted(self):
        for index in range(len(CATEGORY_ICONS) + 1):
            self.add(str(index), None)
        self.assertEqual({row['category_icon'] for row in self.rows()}, set(CATEGORY_ICONS))

    def test_category_icon_is_read_only(self):
        tool = self.add()
        before = self.rows()
        self.assertEqual(self.client.patch(f'/api/ai_nav_flat?eq_id={tool}', json={'category_icon': '<svg/>'}).status_code, 400)
        self.assertEqual(self.client.post('/api/ai_nav_flat', json={'category': 'B', 'category_icon': 'folder'}).status_code, 400)
        self.assertEqual(self.rows(), before)

    def test_create_edit_move_and_delete_tool_preserves_empty_category(self):
        tool = self.add()
        self.add('B', None)
        response = self.client.patch('/api/ai_nav_flat', query_string={'eq_id': tool},
                                     json={'category': 'B', 'name': 'Changed', 'url': 'https://example.com'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual({row['category'] for row in self.rows()}, {'A', 'B'})
        changed = next(row for row in self.rows() if row['id'] == tool)
        self.assertEqual(changed['category_sort_order'], 1)
        self.assertEqual(changed['name'], 'Changed')
        self.assertEqual(self.client.delete('/api/ai_nav_flat', query_string={'eq_id': tool}).status_code, 200)
        self.assertTrue(all(row['name'] is None for row in self.rows()))
        self.assertEqual(self.client.delete('/api/ai_nav_flat?eq_category=A').get_json(), {'deleted': 1})
        self.assertEqual({row['category'] for row in self.rows()}, {'B'})

    def test_rename_handles_quotes_and_rejects_collision(self):
        self.add("A's <tools>")
        self.add('B')
        response = self.client.patch('/api/ai_nav_flat', query_string={'eq_category': "A's <tools>"}, json={'category': '__proto__'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.patch('/api/ai_nav_flat?eq_category=__proto__', json={'category': 'B'}).status_code, 409)
        self.assertEqual({row['category'] for row in self.rows()}, {'__proto__', 'B'})

    def test_category_reorder_preserves_tool_order_and_new_tool_category_rank(self):
        self.add('A', 'One', sort_order=4)
        self.add('A', 'Two', sort_order=9)
        self.add('B', 'Three', sort_order=2)
        result = self.client.post('/api/reorder', json={'kind': 'categories', 'order': ['B', 'A']})
        self.assertEqual(result.status_code, 200)
        self.assertEqual([row['sort_order'] for row in self.rows() if row['category'] == 'A'], [4, 9])
        self.add('A', 'Four')
        self.assertEqual([row['category_sort_order'] for row in self.rows() if row['category'] == 'A'], [1, 1, 1])
        self.assertEqual(self.rows()[0]['category'], 'B')

    def test_equal_tool_order_move_persists_across_restart(self):
        first = self.add(sort_order=1)
        second = self.add(name='Second', sort_order=1)
        result = self.client.post('/api/reorder', json={'kind': 'tools', 'category': 'A', 'order': [second, first]})
        self.assertEqual(result.status_code, 200)
        client = create_app(self.config).test_client()
        self.assertEqual([row['id'] for row in client.get('/api/ai_nav_flat').get_json()], [second, first])

    def test_reorder_rejects_stale_duplicate_or_foreign_ids_without_partial_writes(self):
        first = self.add()
        second = self.add(name='Second')
        foreign = self.add('B', 'Foreign')
        before = self.rows()
        for order, status in [([second], 409), ([first, first], 400), ([second, foreign], 409), ([[first]], 400), ([True], 400)]:
            response = self.client.post('/api/reorder', json={'kind': 'tools', 'category': 'A', 'order': order})
            self.assertEqual(response.status_code, status)
            self.assertEqual(self.rows(), before)

    def test_batch_insert_rolls_back_on_category_conflict(self):
        self.add('A', None)
        before = self.rows()
        response = self.client.post('/api/ai_nav_flat', json=[{'category': 'B', 'name': None}, {'category': 'A', 'name': None}])
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.rows(), before)

    def test_invalid_json_shapes_and_fields_are_client_errors(self):
        for payload in (None, [], [None], 'string', 42, {}, {'category': 'A', 'name': ''},
                        {'category': 'A', 'name': 4}, {'category': 'A', 'sort_order': True},
                        {'category': 'A', 'sort_order': 2**64}, {'category': 'A', 'id': 10}):
            response = self.client.post('/api/ai_nav_flat', json=payload)
            self.assertIn(response.status_code, (400, 415), payload)
        for payload in ([], ['bad'], 42, {'_eq': {'id': 1}}):
            self.assertEqual(self.client.patch('/api/ai_nav_flat?eq_id=1', json=payload).status_code, 400)
        self.assertEqual(self.rows(), [])

    def test_unsafe_urls_and_unfiltered_writes_are_rejected(self):
        tool = self.add()
        for url in ('javascript:alert(1)', 'data:text/html,bad', '//example.com', 'https://[bad', 'https://'):
            self.assertEqual(self.client.patch(f'/api/ai_nav_flat?eq_id={tool}', json={'url': url}).status_code, 400)
        for query in ('', '?eq_fake=x', '?eq_id=1&eq_id=2', '?eq_id=1&unexpected=x'):
            self.assertEqual(self.client.delete('/api/ai_nav_flat' + query).status_code, 400)
        self.assertEqual(self.client.patch('/api/ai_nav_flat?eq_category=A', json={'sort_order': 2}).status_code, 400)
        self.assertEqual(len(self.rows()), 1)

    def test_missing_records_return_not_found(self):
        self.assertEqual(self.client.patch('/api/ai_nav_flat?eq_id=999', json={'name': 'New'}).status_code, 404)
        self.assertEqual(self.client.delete('/api/ai_nav_flat?eq_id=999').status_code, 404)

    def test_repeated_uploads_are_unique_and_retrievable(self):
        image = io.BytesIO()
        Image.new('RGB', (4, 4), 'purple').save(image, format='PNG')
        urls = []
        for _ in range(2):
            response = self.client.post('/api/upload', data={'file': (io.BytesIO(image.getvalue()), '../../test.png')})
            self.assertEqual(response.status_code, 201)
            urls.append(response.get_json()['url'])
            with self.client.get(urls[-1]) as loaded:
                self.assertEqual(loaded.data, image.getvalue())
                self.assertIn('sandbox', loaded.headers['Content-Security-Policy'])
        self.assertNotEqual(urls[0], urls[1])

    def test_upload_rejects_wrong_content_missing_and_oversized_files(self):
        self.assertEqual(self.client.post('/api/upload', data={}).status_code, 400)
        for filename, content in [('fake.png', b'<html>bad</html>'), ('script.html', b'<html>'),
                                  ('bad.svg', b'<html/>'), ('entity.svg', b'<!DOCTYPE svg><svg/>')]:
            self.assertEqual(self.client.post('/api/upload', data={'file': (io.BytesIO(content), filename)}).status_code, 400)
        self.app.config['MAX_CONTENT_LENGTH'] = 1024
        response = self.client.post('/api/upload', data={'file': (io.BytesIO(b'x' * 2048), 'huge.png')})
        self.assertEqual(response.status_code, 413)
        self.assertIn('error', response.get_json())

    def test_corrupt_png_checksum_is_a_client_error(self):
        content = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j4l8AAAAASUVORK5CYII=')
        response = self.client.post('/api/upload', data={'file': (io.BytesIO(content), 'corrupt.png')})
        self.assertEqual(response.status_code, 400)

    def test_svg_upload_uses_sandbox_even_when_opened_directly(self):
        content = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
        response = self.client.post('/api/upload', data={'file': (io.BytesIO(content), 'logo.svg')})
        self.assertEqual(response.status_code, 201)
        with self.client.get(response.get_json()['url']) as loaded:
            self.assertIn("default-src 'none'", loaded.headers['Content-Security-Policy'])
            self.assertIn('sandbox', loaded.headers['Content-Security-Policy'])


class MigrationTests(unittest.TestCase):
    def test_legacy_database_preserves_all_fields_and_migrates_once(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / 'old.db')
            with sqlite3.connect(database) as db:
                db.execute('''CREATE TABLE ai_nav_flat (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL DEFAULT '',
                    name TEXT, logo TEXT DEFAULT '', description TEXT DEFAULT '', url TEXT DEFAULT '',
                    sort_order INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now'))
                )''')
                db.executemany('INSERT INTO ai_nav_flat(category,name,sort_order,logo) VALUES (?,?,?,?)',
                               [('B', 'Tool B', 8, '🧠'), ('A', None, 1, ''), ('A', 'Tool A', 3, '/uploads/old.png')])
                db.row_factory = sqlite3.Row
                before = [dict(row) for row in db.execute('SELECT * FROM ai_nav_flat ORDER BY id')]
            config = {'TESTING': True, 'DATABASE': database, 'UPLOAD_FOLDER': str(Path(directory) / 'uploads')}
            saved_icons = None
            for _ in range(2):
                rows = create_app(config).test_client().get('/api/ai_nav_flat').get_json()
                self.assertEqual(list(dict.fromkeys(row['category'] for row in rows)), ['A', 'B'])
                icons = {row['category']: row['category_icon'] for row in rows}
                self.assertTrue(set(icons.values()) <= set(CATEGORY_ICONS))
                self.assertEqual(len(set(icons.values())), 2)
                for row in rows:
                    self.assertEqual(row['category_icon'], icons[row['category']])
                if saved_icons is not None:
                    self.assertEqual(icons, saved_icons)
                saved_icons = icons
                self.assertEqual([{key: value for key, value in row.items() if key not in {'category_sort_order', 'category_icon'}}
                                  for row in sorted(rows, key=lambda row: row['id'])], before)


if __name__ == '__main__':
    unittest.main()
