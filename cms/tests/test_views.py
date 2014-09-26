import arrow
from datetime import timedelta
import os
from pyramid import testing

from cms.views import CmsViews
from cms.tests.utils import BaseTestCase, RepoHelper


class TestViews(BaseTestCase):

    def setUp(self):
        super(TestViews, self).setUp()
        self.repo = RepoHelper.create(os.path.join(os.getcwd(), '.test_repo'))
        self.config = testing.setUp(settings={
            'git.path': self.repo.path,
            'git.content_repo_url': '',
            'available_languages': 'eng_UK:English swh_KE:Swahili',
        })
        self.views = CmsViews({}, testing.DummyRequest())

    def tearDown(self):
        self.repo.destroy()
        testing.tearDown()

    def test_get_pages_count(self):
        self.repo.create_pages(count=10)
        pages = self.views.get_pages(limit=7)
        self.assertEqual(len(pages), 7)

    def test_get_pages_order_by(self):
        self.repo.create_pages(count=10)
        pages = self.views.get_pages(limit=2, order_by=('title',))
        self.assertEqual(
            [p['title'] for p in pages],
            ['Test Page 0', 'Test Page 1'])

    def test_get_pages_reversed(self):
        self.repo.create_pages(
            count=10,
            timestamp_cb=lambda i: (
                arrow.utcnow() - timedelta(days=i)).isoformat())
        pages = self.views.get_pages(limit=2, reverse=True)
        self.assertEqual(
            [p['title'] for p in pages],
            ['Test Page 0', 'Test Page 1'])

    def test_get_available_languages(self):
        languages = self.views.get_available_languages
        self.assertEqual(languages[0]['code'], 'eng_UK')
        self.assertEqual(languages[1]['code'], 'swh_KE')

    def test_get_featured_category_pages(self):
        category1, category2 = self.repo.create_categories()
        pages = self.repo.create_pages(count=10)

        for page in pages[:8]:
            page.primary_category = category1
            page.save(True, message='Added category.')

        for page in pages[8:]:
            page.primary_category = category1
            page.featured_in_category = True
            page.save(True, message='Added category & set featured.')

        page1, page2 = self.views.get_featured_category_pages(category1.uuid)
        self.assertEqual(
            set([page1['title'], page2['title']]),
            set(['Test Page 8', 'Test Page 9']))
        self.assertEqual(
            [], self.views.get_featured_category_pages(category2.uuid))
