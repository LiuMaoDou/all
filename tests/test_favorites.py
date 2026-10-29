"""Favorites persistence, validation, and migration regression tests."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_api import create_app, CATEGORY_ICONS


class FavoritesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.config = {'TESTING': True, 'DATABASE': str(Path(self.directory.name) / 'favorites.db'),
                       'UPLOAD_FOLDER': str(Path(self.directory.name) / 'uploads')}
        self.client = create_app(self.config).test_client()

    def snapshot(self):
        response = self.client.get('/api/favorites')
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def folder(self, name='开发资源'):
        response = self.client.post('/api/favorite-folders', json={'name': name})
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def bookmark(self, name='GitHub', folder_id=None):
        response = self.client.post('/api/favorites', json={'name': name, 'url': 'https://github.com', 'folder_id': folder_id})
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def test_snapshot_starts_empty_and_assets_are_served(self):
        self.assertEqual(self.snapshot(), {'folders': [], 'bookmarks': []})
        self.assertEqual(self.client.get('/api/favorites').headers['Cache-Control'], 'no-store')
        for asset in ('/favorites.js', '/favorites.css'):
            with self.client.get(asset) as response:
                self.assertEqual(response.status_code, 200)

    def test_create_rename_move_and_restart_preserve_icon_and_date(self):
        source, destination = self.folder(), self.folder('学习资料')
        with patch('favorites_api.secrets.choice', side_effect=lambda options: options[-1]) as random:
            first = self.bookmark(folder_id=source['id'])
            second = self.bookmark(name='Python 官方文档')
            self.assertEqual(random.call_count, 2)
        self.assertIn(first['icon'], CATEGORY_ICONS)
        self.assertNotEqual(first['icon'], second['icon'])
        self.assertTrue(first['created_at'].endswith('Z'))
        self.assertEqual(self.client.patch(f"/api/favorite-folders/{source['id']}", json={'name': '工作资料'}).status_code, 200)
        changed = self.client.patch(f"/api/favorites/{first['id']}", json={'name': 'GitHub Docs', 'folder_id': destination['id'], 'url': 'https://docs.github.com'}).get_json()
        self.assertEqual(changed['icon'], first['icon'])
        self.assertEqual(changed['created_at'], first['created_at'])
        self.assertEqual(changed['folder_id'], destination['id'])
        before = self.snapshot()
        self.assertEqual(create_app(self.config).test_client().get('/api/favorites').get_json(), before)

    def test_deleting_folder_keeps_bookmarks_in_unfiled(self):
        folder = self.folder()
        bookmark = self.bookmark(folder_id=folder['id'])
        self.assertEqual(self.client.delete(f"/api/favorite-folders/{folder['id']}").status_code, 200)
        snapshot = self.snapshot()
        self.assertEqual(snapshot['folders'], [])
        self.assertEqual(len(snapshot['bookmarks']), 1)
        saved = snapshot['bookmarks'][0]
        self.assertIsNone(saved['folder_id'])
        self.assertEqual(saved['icon'], bookmark['icon'])
        self.assertEqual(saved['created_at'], bookmark['created_at'])
        self.assertEqual(self.client.delete(f"/api/favorites/{bookmark['id']}").status_code, 200)
        self.assertEqual(self.snapshot()['bookmarks'], [])

    def test_folder_names_and_collisions(self):
        first, second = self.folder('Work'), self.folder('Study')
        self.assertEqual(self.client.post('/api/favorite-folders', json={'name': 'work'}).status_code, 409)
        self.assertEqual(self.client.patch(f"/api/favorite-folders/{second['id']}", json={'name': 'WORK'}).status_code, 409)
        self.assertEqual(self.client.patch(f"/api/favorite-folders/{first['id']}", json={'name': 'Work'}).status_code, 200)
        for name in ('', ' ', '未分类', '全部收藏', 'x' * 121, None, 1):
            self.assertEqual(self.client.post('/api/favorite-folders', json={'name': name}).status_code, 400)

    def test_unsafe_urls_invalid_shapes_and_read_only_fields(self):
        bookmark = self.bookmark()
        before = self.snapshot()
        payloads = [[], {}, {'name': ''}, {'name': 2}, {'name': 'x' * 201}, {'url': 'javascript:alert(1)'},
                    {'url': 'data:text/html,bad'}, {'url': '//example.com'}, {'url': 'https://[bad'},
                    {'url': 'https://'}, {'url': 'https://example.com/a\nb'}, {'url': 'x' * 4097},
                    {'folder_id': True}, {'folder_id': '1'}, {'folder_id': 999}, {'folder_id': -1},
                    {'icon': '<svg/>'}, {'created_at': '2020-01-01'}, {'id': 8}]
        for data in payloads:
            with self.subTest(data=data):
                self.assertEqual(self.client.patch(f"/api/favorites/{bookmark['id']}", json=data).status_code, 400)
        for data in (None, [], {}, {'name': 'Only name'}, {'url': 'https://example.com'}):
            self.assertIn(self.client.post('/api/favorites', json=data).status_code, (400, 415))
        self.assertEqual(self.snapshot(), before)

    def test_missing_records_and_rejected_move_do_not_change_data(self):
        bookmark = self.bookmark()
        before = self.snapshot()
        self.assertEqual(self.client.patch(f"/api/favorites/{bookmark['id']}", json={'name': 'Changed', 'folder_id': 50}).status_code, 400)
        for base in ('/api/favorites', '/api/favorite-folders'):
            self.assertEqual(self.client.delete(base + '/999').status_code, 404)
            self.assertEqual(self.client.patch(base + '/999', json={'name': 'Changed'}).status_code, 404)
        self.assertEqual(self.snapshot(), before)

    def test_tool_directory_data_is_independent(self):
        self.client.post('/api/ai_nav_flat', json={'category': '开发资源', 'name': 'Existing tool'})
        tools = self.client.get('/api/ai_nav_flat').get_json()
        folder = self.folder('开发资源')
        self.bookmark(folder_id=folder['id'])
        self.client.delete(f"/api/favorite-folders/{folder['id']}")
        self.assertEqual(self.client.get('/api/ai_nav_flat').get_json(), tools)
        self.assertEqual(len(self.snapshot()['bookmarks']), 1)


if __name__ == '__main__':
    unittest.main()
