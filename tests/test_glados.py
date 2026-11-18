"""Offline regression tests for the GLaDOS check-in script."""

import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import glados


class CheckinRegressionTests(unittest.TestCase):
    def test_no_cookies_skips_network(self):
        with patch.dict(os.environ, {'GLADOS_USER_AGENT': 'test-browser'}, clear=True):
            with patch.object(glados.requests, 'Session') as session_factory:
                with patch.object(glados, 'push_message') as push:
                    with redirect_stdout(io.StringIO()):
                        self.assertEqual(glados.main(), 0)
        session_factory.assert_not_called()
        push.assert_not_called()

    def test_accounts_continue_after_failure_and_push_once(self):
        environment = {
            'GLADOS_COOKIES': ' first-cookie & & second-cookie & third-cookie ',
            'GLADOS_USER_AGENT': 'test-browser',
            'PUSHPLUS_TOKEN': 'test-push-token',
        }
        session = Mock()
        context = Mock()
        context.__enter__ = Mock(return_value=session)
        context.__exit__ = Mock(return_value=False)
        statuses = [('first@example.test', '3'), RuntimeError('status failed'),
                    ('third@example.test', '7')]
        with patch.dict(os.environ, environment, clear=True):
            with patch.object(glados.requests, 'Session', return_value=context):
                with patch.object(glados, 'status_account', side_effect=statuses) as status:
                    with patch.object(glados, 'checkin_account', return_value='checked in') as checkin:
                        with patch.object(glados, 'push_message') as push:
                            with redirect_stdout(io.StringIO()):
                                self.assertEqual(glados.main(), 0)

        self.assertEqual(status.call_count, 3)
        self.assertEqual(
            [call.args[1]['Cookie'] for call in status.call_args_list],
            ['first-cookie', 'second-cookie', 'third-cookie'],
        )
        self.assertEqual(checkin.call_count, 2)
        self.assertEqual(
            [call.args[1]['Cookie'] for call in checkin.call_args_list],
            ['first-cookie', 'third-cookie'],
        )
        push.assert_called_once_with(
            'test-push-token',
            'first@example.test|剩余：3天|checked in\n'
            'Cookie2|status failed\n'
            'third@example.test|剩余：7天|checked in',
        )

    def test_checkin_posts_expected_payload_and_formats_points(self):
        session = Mock()
        session.post.return_value = Mock(
            status_code=200,
            json=Mock(return_value={
                'code': 0,
                'message': '签到成功',
                'list': [{'balance': '100.50', 'change': '10.00'}],
            }),
        )
        headers = {'Cookie': 'test-cookie', 'User-Agent': 'test-browser'}

        self.assertEqual(glados.checkin_account(session, headers), '签到成功|积分：100|变化：10')
        session.post.assert_called_once_with(
            glados.CHECKIN_URL,
            headers=headers,
            json={'token': 'glados.cloud'},
            timeout=glados.TIMEOUT,
        )

    def test_status_extracts_email_and_whole_days(self):
        session = Mock()
        session.get.return_value = Mock(
            status_code=200,
            json=Mock(return_value={
                'code': 0,
                'data': {'email': 'user@example.test', 'leftDays': '12.75'},
            }),
        )
        headers = {'Cookie': 'test-cookie'}

        self.assertEqual(glados.status_account(session, headers), ('user@example.test', '12'))
        session.get.assert_called_once_with(
            glados.STATUS_URL, headers=headers, timeout=glados.TIMEOUT,
        )

    def test_device_mismatch_includes_both_devices(self):
        session = Mock()
        session.post.return_value = Mock(
            status_code=403,
            json=Mock(return_value={
                'code': 1,
                'reason': 'device-mismatch',
                'loginDevice': 'Windows',
                'currentDevice': 'Linux',
            }),
        )

        result = glados.checkin_account(session, {})

        self.assertIn('登录设备=Windows', result)
        self.assertIn('运行设备=Linux', result)
        self.assertIn('HTTP 403 code 1', result)

    def test_push_without_token_skips_network(self):
        with patch.object(glados.requests, 'get') as get:
            glados.push_message('', 'test content')
        get.assert_not_called()


if __name__ == '__main__':
    unittest.main()
