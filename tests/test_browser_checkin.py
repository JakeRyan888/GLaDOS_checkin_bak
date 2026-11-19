"""Offline tests for browser submission boundaries and result handling."""

from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock

from browser_checkin import BrowserCheckin, _cookies


BASE = 'https://glados.rocks'
COOKIE = 'gld:sess=private-session==; gld:sess.sig=private-signature'
STATUS = {'http': 200, 'code': 0, 'email': 'user@example.test', 'leftDays': '273.75'}
PAYLOAD = {
    'token': 'glados.rocks', 'nonce': 'private-nonce', 'proof': 'private-proof',
    'tsState': 'ok', 'turnstile': 'private-turnstile',
}


def request(payload=None, url=BASE + '/api/user/checkin', method='POST'):
    return SimpleNamespace(url=url, method=method, post_data_json=dict(PAYLOAD) if payload is None else payload)


def browser_fixture(body=None, http=200, statuses=None, outgoing=None,
                    wait_error=None, finish_error=None):
    """Model one page click and its route/response callbacks, without a browser."""
    runner = BrowserCheckin(BASE, 'test-browser')
    runner.browser = Mock()
    context = Mock()
    page = Mock()
    page.url = BASE + '/console/checkin'
    page.goto.return_value = SimpleNamespace(
        status=200, ok=True, header_value=Mock(return_value=None),
    )
    page.evaluate.side_effect = statuses or [dict(STATUS), dict(STATUS)]
    context.new_page.return_value = page
    runner.browser.new_context.return_value = context
    response = Mock(status=http)
    response.request = request()
    response.json.return_value = body if body is not None else {
        'code': 0, 'list': [{'balance': '795.00', 'change': '13.00'}],
    }
    capture = MagicMock()
    capture.__enter__.return_value = SimpleNamespace(value=response)
    if wait_error:
        capture.__exit__.side_effect = wait_error
    page.expect_response.return_value = capture
    finish = MagicMock()
    if finish_error:
        finish.__exit__.side_effect = finish_error
    page.expect_event.return_value = finish
    routes = []

    def click():
        handler = context.route.call_args.args[1]
        for outgoing_request in outgoing if outgoing is not None else [request()]:
            route = Mock()
            route.request = outgoing_request
            handler(route)
            routes.append(route)

    page.locator.return_value.click.side_effect = click
    return runner, context, page, response, routes


class BrowserCheckinTests(unittest.TestCase):
    def test_cookie_scope_preserves_colons_and_equals(self):
        cookies = _cookies(COOKIE, BASE)
        self.assertEqual(cookies[0], {
            'name': 'gld:sess', 'value': 'private-session==', 'url': BASE + '/', 'secure': True,
        })
        for cookie in cookies:
            self.assertNotIn('domain', cookie)

    def test_malformed_or_duplicate_cookies_are_rejected_without_values(self):
        for raw in ('private-cookie', 'gld:sess=private-value',
                    COOKIE + '; gld:sess=private-duplicate',
                    'gld:sess=private\nvalue; gld:sess.sig=private-sig'):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError) as caught:
                    _cookies(raw, BASE)
                self.assertNotIn('private', str(caught.exception))

    def test_success_requires_explicit_success_and_closes_context(self):
        runner, context, page, _, routes = browser_fixture()
        result = runner.checkin(COOKIE, expected_email='user@example.test')
        self.assertTrue(result.ok)
        self.assertTrue(result.submitted)
        self.assertFalse(result.unknown)
        self.assertEqual(result.email, 'user@example.test')
        self.assertEqual(result.days, '273')
        self.assertIn('13', result.message)
        context.close.assert_called_once()
        page.locator.assert_called_once_with('button.ckb')
        page.locator.return_value.click.assert_called_once()
        routes[0].fallback.assert_called_once()

    def test_context_is_new_for_every_account_and_headers_do_not_leak_cookies(self):
        runner, context, _, _, _ = browser_fixture()
        other = browser_fixture()[1]
        runner.browser.new_context.side_effect = [context, other]
        runner.extra_headers = {}
        first = runner.checkin(COOKIE, status_only=True)
        second = runner.checkin(COOKIE.replace('private-session', 'other-session'), status_only=True)
        self.assertTrue(first.ok and second.ok)
        self.assertEqual(runner.browser.new_context.call_count, 2)
        for call in runner.browser.new_context.call_args_list:
            self.assertEqual(call.kwargs['service_workers'], 'block')
            self.assertNotIn('cookie', {key.lower() for key in call.kwargs['extra_http_headers']})
        context.close.assert_called_once()
        other.close.assert_called_once()
        self.assertNotEqual(context.add_cookies.call_args, other.add_cookies.call_args)

    def test_headers_are_filtered_before_applying_globally(self):
        runner = BrowserCheckin(BASE, 'test-browser', {
            'Cookie': 'private-cookie', 'Origin': BASE, 'Referer': BASE,
            'Accept-Language': 'zh-CN', 'Sec-CH-UA-Platform': '"Windows"',
        })
        self.assertEqual(runner.extra_headers, {
            'accept-language': 'zh-CN', 'sec-ch-ua-platform': '"Windows"',
        })

    def test_auth_failure_does_not_click_or_submit(self):
        runner, context, page, _, routes = browser_fixture(statuses=[{
            'http': 200, 'code': -2, 'email': None,
        }])
        result = runner.checkin(COOKIE)
        self.assertFalse(result.ok)
        self.assertFalse(result.submitted)
        self.assertFalse(result.unknown)
        page.locator.assert_not_called()
        self.assertFalse(routes)
        context.close.assert_called_once()

    def test_browser_failures_report_separate_stages_without_raw_errors(self):
        for operation, error, message in (
            ('goto', TimeoutError('private-navigation'), '加载签到页面超时'),
            ('evaluate', ValueError('private-status'), '查询登录状态失败'),
        ):
            with self.subTest(operation=operation):
                runner, context, page, _, routes = browser_fixture()
                getattr(page, operation).side_effect = error
                result = runner.checkin(COOKIE)
                self.assertIn(message, result.message)
                self.assertIn('未提交签到', result.message)
                self.assertNotIn('private-', result.message)
                self.assertFalse(result.ok or result.submitted or result.unknown)
                page.locator.assert_not_called()
                self.assertEqual(routes, [])
                context.close.assert_called_once()

    def test_status_errors_distinguish_authorization_http_and_identity(self):
        cases = [
            ({'http': 200, 'code': -2}, 'HTTP=200 code=-2', '登录会话未获授权'),
            ({'http': 403, 'code': -2}, 'HTTP=403 code=-2', '无法确认登录状态'),
            ({'http': 503, 'code': 7}, 'HTTP=503 code=7', '无法确认登录状态'),
            ({'http': 200, 'code': 0}, 'HTTP=200 code=0', '身份字段缺失或无效'),
            ({'http': 200, 'code': 0, 'email': 'private-email'},
             'HTTP=200 code=0', '身份字段缺失或无效'),
            ({'http': 200, 'invalid': True}, 'HTTP=200 code=未知', '响应格式无效'),
            ({'http': 403, 'failure': 'challenge'}, 'HTTP=403 code=未知', 'Cloudflare 验证'),
            ({'http': 200, 'failure': 'timeout'}, 'HTTP=200 code=未知', '读取超时'),
            ({'failure': 'network'}, 'HTTP=未知 code=未知', '网络请求失败'),
            ({'http': 403, 'invalid': True}, 'HTTP=403 code=未知', '无法确认登录状态'),
            ({'http': 'private-http', 'code': 'private-code'},
             'HTTP=未知 code=未知', '无法确认登录状态'),
            ({'http': 200, 'code': 'private-code'}, 'HTTP=200 code=未知', '状态查询失败'),
            (['private-body'], 'HTTP=未知 code=未知', '响应格式无效'),
        ]
        for status, evidence, description in cases:
            with self.subTest(status=status):
                runner, context, page, _, routes = browser_fixture(statuses=[status])
                result = runner.checkin(COOKIE)
                self.assertFalse(result.ok or result.submitted or result.unknown)
                self.assertIn(evidence, result.message)
                self.assertIn(description, result.message)
                self.assertNotIn('private', result.message)
                if description != '登录会话未获授权':
                    self.assertNotIn('请更新', result.message)
                page.locator.assert_not_called()
                self.assertFalse(routes)
                context.close.assert_called_once()

    def test_changed_or_unexpected_identity_never_clicks(self):
        cases = [
            ([dict(STATUS), {**STATUS, 'email': 'other@example.test'}], None),
            ([dict(STATUS)], 'other@example.test'),
        ]
        for statuses, expected in cases:
            with self.subTest(expected=expected):
                runner, context, page, _, routes = browser_fixture(statuses=statuses)
                result = runner.checkin(COOKIE, expected_email=expected)
                self.assertFalse(result.ok or result.submitted or result.unknown)
                page.locator.return_value.click.assert_not_called()
                self.assertFalse(routes)
                context.close.assert_called_once()

    def test_failed_or_missing_verification_never_reaches_network(self):
        cases = (
            ({**PAYLOAD, 'tsState': 'timeout'}, '页面报告超时'),
            ({**PAYLOAD, 'tsState': 'error'}, '页面报告错误'),
            ({**PAYLOAD, 'tsState': ['private-state']}, '缺少有效的验证状态'),
            ({**PAYLOAD, 'turnstile': ''}, '缺少验证结果'),
            ({**PAYLOAD, 'proof': ''}, '缺少必要的确认字段'),
            ({'token': 'glados.rocks'}, '缺少有效的验证状态'),
            ({**PAYLOAD, 'token': 'glados.cloud'}, '与配置域名不符'),
            (['private-value'], '请求格式不符'),
        )
        for payload, message in cases:
            with self.subTest(payload=payload):
                runner, _, _, _, routes = browser_fixture(outgoing=[request(payload)])
                result = runner.checkin(COOKIE)
                self.assertFalse(result.ok or result.submitted or result.unknown)
                self.assertIn(message, result.message)
                self.assertIn('未提交', result.message)
                self.assertNotIn('private', result.message)
                routes[0].abort.assert_called_once()
                routes[0].fallback.assert_not_called()

    def test_guard_allows_only_one_submission_and_no_initial_submission(self):
        runner, _, _, _, routes = browser_fixture(outgoing=[request(), request()])
        result = runner.checkin(COOKIE)
        self.assertTrue(result.ok)
        routes[0].fallback.assert_called_once()
        routes[1].abort.assert_called_once()
        state = {'armed': False, 'submitted': False, 'blocked': ''}
        route = Mock(request=request())
        runner._guard(route, state)
        route.abort.assert_called_once()
        self.assertFalse(state['submitted'])

    def test_blocked_verification_cannot_be_followed_by_an_automatic_retry(self):
        runner, _, _, _, routes = browser_fixture(outgoing=[
            request({**PAYLOAD, 'tsState': 'timeout'}), request(),
        ])
        result = runner.checkin(COOKIE)
        self.assertFalse(result.ok or result.submitted or result.unknown)
        for route in routes:
            route.abort.assert_called_once()
            route.fallback.assert_not_called()

    def test_response_matcher_rejects_other_hosts_paths_and_methods(self):
        runner = BrowserCheckin(BASE, 'test-browser')
        self.assertTrue(runner._matches(request()))
        for candidate in (request(url=BASE + '/api/user/checkin/challenge'),
                          request(url='https://other.example/api/user/checkin'),
                          request(method='GET')):
            self.assertFalse(runner._matches(candidate))

    def test_guard_blocks_post_path_variants_and_allows_only_challenge_get(self):
        runner = BrowserCheckin(BASE, 'test-browser')
        for path in ('/api/user/checkin/', '/api/user/checkin/challenge',
                     '/api/user/checkin-retry'):
            with self.subTest(path=path):
                state = {'armed': True, 'submitted': False, 'blocked': ''}
                route = Mock(request=request(url=BASE + path))
                runner._guard(route, state)
                route.abort.assert_called_once()
                route.fallback.assert_not_called()
                self.assertFalse(state['submitted'] or state['armed'])
        state = {'armed': False, 'submitted': False, 'blocked': ''}
        route = Mock(request=request(url=BASE + '/api/user/checkin/challenge', method='GET'))
        runner._guard(route, state)
        route.fallback.assert_called_once()
        route.abort.assert_not_called()
        self.assertFalse(state['submitted'])

    def test_timeout_after_submission_is_unknown_and_not_retried(self):
        runner, context, page, _, routes = browser_fixture(wait_error=TimeoutError('private-data'))
        result = runner.checkin(COOKIE)
        self.assertFalse(result.ok)
        self.assertTrue(result.submitted and result.unknown)
        self.assertIn('结果未知', result.message)
        self.assertNotIn('private', result.message)
        page.locator.return_value.click.assert_called_once()
        self.assertEqual(len(routes), 1)
        context.close.assert_called_once()

    def test_timeout_before_submission_is_known_not_submitted(self):
        runner, _, _, _, _ = browser_fixture(outgoing=[], wait_error=TimeoutError('private-data'))
        result = runner.checkin(COOKIE)
        self.assertFalse(result.ok or result.submitted or result.unknown)
        self.assertIn('未提交', result.message)
        self.assertNotIn('private', result.message)

    def test_stalled_response_body_is_unknown_without_reading_or_retrying(self):
        runner, context, page, response, routes = browser_fixture(
            finish_error=TimeoutError('private-body'),
        )
        result = runner.checkin(COOKIE)
        self.assertTrue(result.submitted and result.unknown)
        self.assertFalse(result.ok)
        self.assertIn('结果未知', result.message)
        self.assertNotIn('private', result.message)
        response.json.assert_not_called()
        page.expect_event.assert_called_once()
        event_args = page.expect_event.call_args
        self.assertEqual(event_args.args[0], 'requestfinished')
        self.assertEqual(event_args.kwargs['timeout'], runner.timeout_ms)
        self.assertTrue(event_args.kwargs['predicate'](request()))
        page.locator.return_value.click.assert_called_once()
        self.assertEqual(len(routes), 1)
        context.close.assert_called_once()

    def test_error_code_with_old_history_is_failure(self):
        runner, _, _, _, _ = browser_fixture(body={
            'code': 5, 'reason': 'turnstile',
            'message': 'private-server-value',
            'list': [{'balance': '795', 'change': '13'}],
        })
        result = runner.checkin(COOKIE)
        self.assertFalse(result.ok or result.unknown)
        self.assertTrue(result.submitted)
        self.assertIn('Turnstile', result.message)
        self.assertNotIn('795', result.message)
        self.assertNotIn('private', result.message)

    def test_repeated_result_does_not_claim_new_reward(self):
        runner, _, _, _, _ = browser_fixture(body={
            'code': 0, 'repeated': True,
            'list': [{'balance': '795', 'change': '13'}],
        })
        result = runner.checkin(COOKIE)
        self.assertTrue(result.ok)
        self.assertIn('未确认新增积分', result.message)
        self.assertNotIn('13', result.message)

    def test_boolean_false_is_not_accepted_as_success_code(self):
        runner, _, _, _, _ = browser_fixture(body={'code': False})
        self.assertFalse(runner.checkin(COOKIE).ok)

    def test_invalid_json_after_submission_is_unknown(self):
        runner, _, _, response, _ = browser_fixture()
        response.json.side_effect = ValueError('private-body')
        result = runner.checkin(COOKIE)
        self.assertTrue(result.submitted and result.unknown)
        self.assertFalse(result.ok)
        self.assertNotIn('private', result.message)

    def test_status_only_never_arms_or_clicks(self):
        runner, context, page, _, routes = browser_fixture()
        result = runner.checkin(COOKIE, status_only=True)
        self.assertTrue(result.ok)
        self.assertFalse(result.submitted or result.unknown)
        self.assertIn('只读', result.message)
        page.expect_response.assert_not_called()
        self.assertFalse(routes)
        context.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
