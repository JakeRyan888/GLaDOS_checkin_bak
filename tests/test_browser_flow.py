"""Exercise the adapter in real Chrome against intercepted, offline fixtures."""

import json
import unittest
from urllib.parse import urlsplit

from browser_checkin import BrowserCheckin


BASE = 'https://glados.rocks'
COOKIE = 'gld:sess=session-one; gld:sess.sig=fixture-signature'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36')


class FixtureBrowser:
    def __init__(self, browser, *, verification='ok', duplicate=False, failure=False,
                 invalid_json=False, auth_failure=False):
        self.browser = browser
        self.verification = verification
        self.duplicate = duplicate
        self.failure = failure
        self.invalid_json = invalid_json
        self.auth_failure = auth_failure
        self.posts = []
        self.status_cookies = []
        self.closed = []
        self.challenge_count = 0

    def new_context(self, **kwargs):
        context = self.browser.new_context(**kwargs)
        context.on('close', lambda _: self.closed.append(True))
        context.route('**/*', self.serve)
        return context

    def serve(self, route):
        request = route.request
        path = urlsplit(request.url).path
        headers = {'Content-Type': 'application/json'}
        if path == '/console/checkin':
            html = '''<!doctype html><meta charset="utf-8"><button class="ckb">签到</button>
            <script>
            document.querySelector('button.ckb').onclick = async () => {
              const challenge = await (await fetch('/api/user/checkin/challenge')).json();
              const payload = {token: location.hostname, nonce: challenge.nonce,
                proof: 'fixture-proof', tsState: VERIFICATION, turnstile: 'fixture-token'};
              const send = () => fetch('/api/user/checkin', {method:'POST',
                headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
              try { await send(); } catch (e) {}
              if (DUPLICATE) { try { await send(); } catch (e) {} }
            };
            </script>'''
            html = html.replace('VERIFICATION', json.dumps(self.verification))
            html = html.replace('DUPLICATE', json.dumps(self.duplicate))
            route.fulfill(status=200, content_type='text/html', body=html)
            return
        if path == '/api/user/status':
            cookie = request.headers.get('cookie', '')
            self.status_cookies.append(cookie)
            email = 'two@example.test' if 'session-two' in cookie else 'one@example.test'
            body = {'code': -2} if self.auth_failure else {
                'code': 0, 'data': {'email': email, 'leftDays': '273.75'},
            }
            headers['Set-Cookie'] = 'fixture_marker=one; Path=/; Secure'
        elif path == '/api/user/checkin/challenge':
            self.challenge_count += 1
            body = {'code': 0, 'nonce': f'fixture-nonce-{self.challenge_count}'}
        elif path == '/api/user/checkin' and request.method == 'POST':
            self.posts.append(request.post_data_json)
            if self.invalid_json:
                route.fulfill(status=200, content_type='text/plain', body='not JSON')
                return
            body = {'code': 5, 'reason': 'turnstile'} if self.failure else {'code': 0}
            body['list'] = [{'balance': '795.00', 'change': '13.00'}]
        else:
            route.abort()
            return
        route.fulfill(status=200, headers=headers, body=json.dumps(body))


class RealBrowserFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
            cls.playwright = sync_playwright().start()
            cls.browser = cls.playwright.chromium.launch(channel='chrome', headless=True)
        except Exception:
            if hasattr(cls, 'playwright'):
                cls.playwright.stop()
            raise unittest.SkipTest('Fixture integration requires Playwright and installed Google Chrome') from None

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def runner(self, **scenario):
        fixture = FixtureBrowser(self.browser, **scenario)
        runner = BrowserCheckin(BASE, UA, headless=True, timeout=2)
        runner.browser = fixture
        return runner, fixture

    def test_official_page_flow_submits_new_challenge_exactly_once(self):
        runner, fixture = self.runner(duplicate=True)
        result = runner.checkin(COOKIE, expected_email='one@example.test')
        self.assertTrue(result.ok, result.message)
        self.assertTrue(result.submitted)
        self.assertEqual(len(fixture.posts), 1)
        self.assertEqual(fixture.posts[0]['nonce'], 'fixture-nonce-1')
        self.assertEqual(fixture.posts[0]['tsState'], 'ok')
        self.assertEqual(len(fixture.closed), 1)

    def test_isolated_accounts_do_not_share_response_cookies(self):
        runner, fixture = self.runner()
        first = runner.checkin(COOKIE, status_only=True)
        second = runner.checkin(COOKIE.replace('session-one', 'session-two'), status_only=True)
        self.assertTrue(first.ok and second.ok)
        self.assertEqual(first.email, 'one@example.test')
        self.assertEqual(second.email, 'two@example.test')
        self.assertEqual(len(fixture.status_cookies), 2)
        self.assertNotIn('fixture_marker', fixture.status_cookies[1])
        self.assertEqual(fixture.posts, [])
        self.assertEqual(len(fixture.closed), 2)

    def test_identity_mismatch_stops_before_challenge_or_submission(self):
        runner, fixture = self.runner()
        result = runner.checkin(COOKIE, expected_email='other@example.test')
        self.assertFalse(result.ok or result.submitted or result.unknown)
        self.assertEqual(fixture.posts, [])
        self.assertEqual(fixture.challenge_count, 0)

    def test_failed_widget_state_is_blocked_before_network(self):
        runner, fixture = self.runner(verification='timeout', duplicate=True)
        result = runner.checkin(COOKIE)
        self.assertFalse(result.ok or result.submitted or result.unknown)
        self.assertEqual(fixture.posts, [])

    def test_business_rejection_with_history_is_failure(self):
        runner, fixture = self.runner(failure=True)
        result = runner.checkin(COOKIE)
        self.assertFalse(result.ok or result.unknown)
        self.assertTrue(result.submitted)
        self.assertEqual(len(fixture.posts), 1)
        self.assertIn('Turnstile', result.message)
        self.assertNotIn('795', result.message)

    def test_invalid_response_is_unknown_without_retry(self):
        runner, fixture = self.runner(invalid_json=True, duplicate=True)
        result = runner.checkin(COOKIE)
        self.assertFalse(result.ok)
        self.assertTrue(result.submitted and result.unknown)
        self.assertEqual(len(fixture.posts), 1)


if __name__ == '__main__':
    unittest.main()
