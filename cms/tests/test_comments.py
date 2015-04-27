import time
from unittest import TestCase
from datetime import datetime
from dateutil import parser as dt_parser
import pytz
import uuid

import mock
from deform import ValidationFailure

from pyramid import testing
from pyramid_beaker import set_cache_regions_from_settings

from unicore.hub.client import User
from unicore.comments.client import (
    CommentClient, LazyCommentPage, UserBanned, CommentStreamNotOpen)
from unicore.content.models import Page
from cms.tests.base import UnicoreTestCase
from cms.views.forms import (
    CommentForm, COMMENT_STALE_AFTER, COMMENT_MAX_LENGTH)
from cms.views.cms_views import CmsViews, COMMENTS_PER_PAGE


class TestCommentViews(UnicoreTestCase):

    def setUp(self):
        self.workspace = self.mk_workspace()
        settings = self.get_settings(self.workspace, **{
            'unicorecomments.host': 'http://localhost/commentservice'})

        self.config = testing.setUp(settings=settings)
        self.config.include('cms')
        set_cache_regions_from_settings(settings)

        self.views = CmsViews(testing.DummyRequest())
        self.app_id = settings['unicorehub.app_id']
        self.app = self.mk_app(self.workspace, settings=settings)

        [category] = self.create_categories(self.workspace, count=1)
        [page] = self.create_pages(
            self.workspace, count=1, description='description',
            primary_category=category.uuid)
        self.page = page
        self.stream = self.mk_comment_stream(
            page.uuid, state='open', offset=10, limit=5)

        self.patch_lazy_comment_page = mock.patch.object(
            LazyCommentPage, 'data',
            new=mock.PropertyMock(return_value=self.stream))
        self.patch_lazy_comment_page.start()

    def tearDown(self):
        testing.tearDown()
        self.patch_lazy_comment_page.stop()

    def mk_comment(self, content_uuid, **fields):
        data = {
            'uuid': uuid.uuid4().hex,
            'user_uuid': uuid.uuid4().hex,
            'content_uuid': content_uuid,
            'app_uuid': self.app_id,
            'comment': 'this is a comment',
            'user_name': 'foo',
            'submit_datetime': datetime.now(pytz.utc).isoformat(),
            'content_type': 'page',
            'content_title': 'I Am A Page',
            'content_url': 'http://example.com/page/',
            'locale': 'eng_ZA',
            'flag_count': '0',
            'is_removed': 'False',
            'moderation_state': 'visible',
            'ip_address': '192.168.1.1'
        }
        data.update(fields)
        return data

    def mk_comment_stream(self, content_uuid, limit=10, offset=0, state='open',
                          total=100, **comment_fields):
        return {
            'start': offset,
            'end': offset + limit,
            'total': total,
            'count': limit,
            'objects': [self.mk_comment(content_uuid, **comment_fields)
                        for i in range(limit)],
            'metadata': {'state': state}
        }

    @mock.patch.object(LazyCommentPage, '__init__')
    def test_get_comments_for_content(self, mock_init):
        content_uuid = 'content_uuid'
        mock_init.return_value = None
        page_obj = self.views.get_comments_for_content(content_uuid)

        self.assertIsInstance(page_obj, LazyCommentPage)
        mock_init.assert_called_with(
            self.config.registry.commentclient,
            content_uuid=content_uuid,
            app_uuid=self.app_id,
            limit=COMMENTS_PER_PAGE)

        self.views.request.GET['c_after'] = 'after_uuid'
        page_obj = self.views.get_comments_for_content(
            content_uuid, limit=1)

        self.assertIsInstance(page_obj, LazyCommentPage)
        mock_init.assert_called_with(
            self.config.registry.commentclient,
            content_uuid=content_uuid,
            app_uuid=self.app_id,
            limit=1,
            after='after_uuid')

        del self.views.request.GET['c_after']
        self.views.request.GET['c_before'] = 'before_uuid'
        page_obj = self.views.get_comments_for_content(content_uuid)

        self.assertIsInstance(page_obj, LazyCommentPage)
        mock_init.assert_called_with(
            self.config.registry.commentclient,
            content_uuid=content_uuid,
            app_uuid=self.app_id,
            limit=COMMENTS_PER_PAGE,
            before='before_uuid')

        self.views.request.registry.commentclient = None
        page_obj = self.views.get_comments_for_content(content_uuid)

        self.assertIs(page_obj, None)

    def check_comment_list(self, root):
        uuid = self.stream['objects'][0]['content_uuid']

        header = root.select('.comments-header')[0]
        self.assertIn('%d comments' % self.stream['total'], header.string)
        prev, nxt = root.select('.comments-pagination > a')
        self.assertIn('Previous', prev.string)
        self.assertIn(
            '/content/comments/%s/?c_after' % uuid, prev['href'])
        self.assertIn('Next', nxt.string)
        self.assertIn(
            '/content/comments/%s/?c_before' % uuid, nxt['href'])
        li = root.select('.comment-list > .comment')
        self.assertEqual(len(li), len(self.stream['objects']))
        comment_obj = self.stream['objects'][0]
        comment_el = li[0]
        self.assertTrue(comment_el.select('.comment-author'))
        self.assertEqual(
            comment_el.select('.comment-author')[0].string,
            comment_obj['user_name'])
        self.assertTrue(comment_el.select('.comment-meta > .date'))
        self.assertTrue(
            comment_el.select('.comment-meta > .date')[0].string)
        self.assertTrue(comment_el.select('p'))
        self.assertEqual(
            comment_el.select('p')[0].string, comment_obj['comment'])

    def check_comment_form(self, root):
        uuid = self.stream['objects'][0]['content_uuid']

        form = root.select('#add-comment > form')
        self.assertTrue(form)
        form = form[0]
        self.assertIn('/content/comments/%s/' % uuid, form['action'])
        self.assertEqual(len(form.select('input')), 5)
        self.assertEqual(len(form.select('textarea')), 1)

    def test_comments_404(self):
        response = self.app.get(
            '/content/comments/%s/' % uuid.uuid4().hex, expect_errors=True)
        self.assertEqual(response.status_int, 404)

        response = self.app.get(
            '/content/comments/%s/?_LOCALE_=swa_KE' % self.page.uuid,
            expect_errors=True)
        self.assertEqual(response.status_int, 404)

    def test_comments_open_stream_logged_out(self):
        response = self.app.get('/content/comments/%s/' % self.page.uuid)
        self.check_comment_list(response.html)
        not_signed_in = response.html.select('#add-comment > p')
        self.assertTrue(not_signed_in)
        self.assertIn(
            'You have to be signed in to add a comment',
            not_signed_in[0].text)
        self.assertFalse(response.html.select('#add-comment > form'))

    def test_comments_open_stream_logged_in(self):
        response = self.app.get(
            '/content/comments/%s/' % self.page.uuid,
            headers=self.mk_session()[1])
        self.check_comment_form(response.html)

    def test_comments_closed_stream(self):
        self.stream['metadata']['state'] = 'closed'
        response = self.app.get('/content/comments/%s/' % self.page.uuid)
        not_open = response.html.select('#add-comment > p')
        self.assertTrue(not_open)
        self.assertIn(
            'Commenting has been closed', not_open[0].string)
        self.assertFalse(response.html.select('#add-comment > form'))

    def test_comments_disabled_stream(self):
        for meta in ({'state': 'disabled'}, {}):
            self.stream['metadata'] = meta
            response = self.app.get('/content/comments/%s/' % self.page.uuid)
            for selector in ('#add-comment *', '.comment-list',
                             '.comments-header', '.comments-pagination'):
                self.assertFalse(response.html.select(selector))

    def test_content_with_comments(self):
        # NOTE: Chameleon templates don't have commenting nor
        # will commenting be added to them
        response = self.app.get(
            '/spice/content/detail/%s/' % self.page.uuid,
            headers=self.mk_session()[1])
        self.check_comment_list(response.html)
        self.check_comment_form(response.html)

    def test_post_comment(self):
        mock_create_comment = mock.Mock()
        patch_client = mock.patch.object(
            self.app.app.registry.commentclient, 'create_comment',
            new=mock_create_comment)
        patch_client.start()

        self.stream['objects'] = []
        self.stream['start'] = None
        self.stream['end'] = None
        self.stream['total'] = 0
        session_cookie = self.mk_session()[1]
        response = self.app.get(
            '/content/comments/%s/' % self.page.uuid,
            headers=session_cookie)
        form = response.forms[0]
        form['comment'] = 'foo bar'

        # no issues
        response = form.submit('submit', headers=session_cookie)
        self.assertEqual(response.status_int, 302)
        self.assertEqual(
            response.location,
            'http://localhost/content/comments/%s/' % self.page.uuid)
        mock_create_comment.assert_called()
        data = mock_create_comment.call_args[0][0]
        self.assertEqual(data.get('comment'), 'foo bar')

        # missing field
        form['comment'] = ''
        response = form.submit('submit', headers=session_cookie)
        self.assertEqual(response.status_int, 200)
        self.assertIn(
            'Required',
            response.html.select('#add-comment > form')[0].text)

        # banned user
        form['comment'] = 'foo bar'
        mock_create_comment.side_effect = UserBanned(mock.MagicMock())
        response = form.submit('submit', headers=session_cookie)
        self.assertEqual(response.status_int, 200)
        self.assertIn(
            'You have been banned from commenting',
            response.html.select('#add-comment > form')[0].text)

        # closed stream
        mock_create_comment.side_effect = CommentStreamNotOpen(
            mock.MagicMock())
        response = form.submit('submit', headers=session_cookie)
        self.assertEqual(response.status_int, 302)

        # ValueError (CSRF failure, no authenticated user, etc)
        mock_create_comment.side_effect = ValueError
        response = form.submit(
            'submit', headers=session_cookie, expect_errors=True)
        self.assertEqual(response.status_int, 400)


class TestCommentForm(TestCase):

    def setUp(self):
        self.request = testing.DummyRequest()
        self.request.route_url = mock.Mock(return_value='content_url')
        self.request.locale_name = 'eng_GB'
        self.request.user = User(None, {
            'uuid': 'user_uuid',
            'app_data': {'display_name': 'Foo'}})
        self.request.session = mock.Mock(
            get_csrf_token=mock.Mock(return_value='csrf_foo'))
        self.request.registry.commentclient = CommentClient(
            app_id='app_uuid', host='host_url')
        self.content_object = Page({
            'uuid': 'content_uuid',
            'title': 'content_title'})
        self.form = CommentForm(self.request, self.content_object)

    def test_no_comment_client(self):
        self.request.registry.commentclient = None
        self.assertRaisesRegexp(
            ValueError, 'No comment client configured', self.form.validate, {})

    def test_no_user(self):
        self.request.user = None
        self.assertRaisesRegexp(
            ValueError, 'No authenticated user', self.form.validate, {})

    def test_security_errors(self):
        cstruct = {
            'comment': 'foo',
            'content_type': 'page',
            'content_uuid': 'content_uuid',
            'timestamp': int(time.time()),
            'csrf': 'csrf_foo'
        }

        def check_error(field, *invalid_values):
            data = cstruct.copy()
            for invalid, msg in invalid_values:
                if invalid == '__del__':
                    del data[field]
                else:
                    data[field] = invalid
                self.assertRaisesRegexp(
                    ValueError, msg, self.form.validate, data.items())

        check_error(
            'content_type',
            ('does_not_match', 'Invalid content type'),
            ('__del__', 'Required'))
        check_error(
            'content_uuid',
            ('does_not_match', 'Invalid content uuid'),
            ('__del__', 'Required'))
        check_error(
            'timestamp',
            ('wrong_type', 'is not a number'),
            (int(time.time()) - COMMENT_STALE_AFTER - 1,
                'Timestamp check failed'),
            ('__del__', 'Required'))
        check_error(
            'csrf',
            ('does_not_match', 'Bad CSRF token'),
            ('__del__', 'Required'))

    def test_validation_failure(self):
        cstruct = {
            'content_type': 'page',
            'content_uuid': 'content_uuid',
            'timestamp': int(time.time()),
            'csrf': 'csrf_foo'
        }
        self.assertRaises(
            ValidationFailure, self.form.validate, cstruct.items())
        cstruct['comment'] = ''
        self.assertRaises(
            ValidationFailure, self.form.validate, cstruct.items())
        cstruct['comment'] = 'c' * (COMMENT_MAX_LENGTH + 1)
        self.assertRaises(
            ValidationFailure, self.form.validate, cstruct.items())

    def test_returned_data(self):
        cstruct = {
            'comment': 'this is a comment',
            'content_type': 'page',
            'content_uuid': 'content_uuid',
            'timestamp': int(time.time()),
            'csrf': 'csrf_foo'
        }
        data = self.form.validate(cstruct.items())

        submit_datetime = data.pop('submit_datetime', None)
        self.assertEqual(
            dt_parser.parse(submit_datetime).date(),
            datetime.now(pytz.utc).date())
        self.assertEqual(data, {
            'app_uuid': 'app_uuid',
            'content_uuid': 'content_uuid',
            'user_uuid': 'user_uuid',
            'comment': 'this is a comment',
            'user_name': 'Foo',
            'content_type': 'page',
            'content_title': 'content_title',
            'content_url': 'content_url',
            'locale': 'eng_GB'
        })

        del self.request.user.get('app_data')['display_name']
        data = self.form.validate(cstruct.items())

        self.assertEqual(data.get('user_name'), 'Anonymous')
