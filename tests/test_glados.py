"""CLI orchestration tests: no network or browser launch."""

import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import requests

import glados
from browser_checkin import AccountResult


class CheckinOrchestrationTests(unittest.TestCase):
    def test_no_cookies_is_configuration_failure_without_browser(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(glados, 'BrowserCheckin') as factory:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(glados.main(), 1)
        factory.assert_not_called()

    def test_accounts_continue_after_failure_and_push_once(self):
        environment = {'GLADOS_COOKIES': ' first-cookie & & second-cookie & third-cookie ',
                       'GLADOS_USER_AGENT': 'test-browser', 'PUSHPLUS_TOKEN': 'test-push-token'}
        results = [AccountResult(email='first@example.test', days='3', ok=True, message='成功'),
                   RuntimeError('private-cookie-and-token'),
                   AccountResult(email='third@example.test', days='7', ok=True, message='成功')]
        output = io.StringIO()
        with patch.dict(os.environ, environment, clear=True), patch.object(glados, 'BrowserCheckin') as factory:
            runner = factory.return_value.__enter__.return_value
            runner.checkin.side_effect = results
            with patch.object(glados, 'push_message') as push, redirect_stdout(output):
                self.assertEqual(glados.main(), 1)
        self.assertEqual([call.args[0] for call in runner.checkin.call_args_list],
                         ['first-cookie', 'second-cookie', 'third-cookie'])
        push.assert_called_once()
        self.assertEqual(push.call_args.args[0], 'test-push-token')
        self.assertIn('third@example.test|剩余：7天|成功', push.call_args.args[1])
        self.assertNotIn('private-cookie-and-token', output.getvalue())

    def test_business_failure_returns_nonzero_and_does_not_stop_next_account(self):
        environment = {'GLADOS_COOKIES': 'one&two', 'GLADOS_USER_AGENT': 'test-browser'}
        with patch.dict(os.environ, environment, clear=True), patch.object(glados, 'BrowserCheckin') as factory:
            runner = factory.return_value.__enter__.return_value
            runner.checkin.side_effect = [AccountResult(ok=False, message='需要人工验证'),
                                         AccountResult(ok=True, message='已签到')]
            with patch.object(glados, 'push_message'), redirect_stdout(io.StringIO()):
                self.assertEqual(glados.main(), 1)
            self.assertEqual(runner.checkin.call_count, 2)

    def test_status_only_does_not_send_notification(self):
        environment = {'GLADOS_COOKIES': 'one', 'GLADOS_USER_AGENT': 'test-browser',
                       'GLADOS_STATUS_ONLY': 'true', 'PUSHPLUS_TOKEN': 'private-token'}
        with patch.dict(os.environ, environment, clear=True), patch.object(glados, 'BrowserCheckin') as factory:
            runner = factory.return_value.__enter__.return_value
            runner.checkin.return_value = AccountResult(ok=True, message='只读检查成功')
            with patch.object(glados, 'push_message') as push, redirect_stdout(io.StringIO()):
                self.assertEqual(glados.main(), 0)
            runner.checkin.assert_called_once_with('one', status_only=True)
            push.assert_not_called()

    def test_browser_launch_error_is_redacted(self):
        environment = {'GLADOS_COOKIES': 'one', 'GLADOS_USER_AGENT': 'test-browser'}
        output = io.StringIO()
        with patch.dict(os.environ, environment, clear=True), patch.object(glados, 'BrowserCheckin') as factory:
            factory.return_value.__enter__.side_effect = RuntimeError('private-browser-details')
            with patch.object(glados, 'push_message'), redirect_stdout(output):
                self.assertEqual(glados.main(), 1)
        self.assertNotIn('private-', output.getvalue())
        self.assertIn('浏览器启动或运行失败', output.getvalue())

    def test_push_without_token_skips_network(self):
        with patch.object(glados.requests, 'get') as get:
            glados.push_message('', 'test content')
        get.assert_not_called()

    def test_push_network_error_does_not_expose_token_url(self):
        output = io.StringIO()
        with patch.object(glados.requests, 'get', side_effect=requests.RequestException('private-token')):
            with redirect_stdout(output):
                glados.push_message('private-token', 'test content')
        self.assertNotIn('private-token', output.getvalue())


if __name__ == '__main__':
    unittest.main()
