"""Browser configuration tests; no live API or notification requests."""

import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch

import requests

import glados


USER_AGENT = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36'
)


class BrowserHeadersTests(unittest.TestCase):
    def test_ua_is_read_from_environment_with_same_origin_metadata(self):
        with patch.dict(os.environ, {'GLADOS_USER_AGENT': USER_AGENT}, clear=True):
            headers = glados.build_headers()
        self.assertEqual(headers['User-Agent'], USER_AGENT)
        self.assertEqual(headers['Sec-Fetch-Site'], 'same-origin')
        self.assertEqual(headers['Sec-Fetch-Mode'], 'cors')
        self.assertEqual(headers['Sec-Fetch-Dest'], 'empty')
        self.assertEqual(headers['Origin'], 'https://glados.cloud')
        self.assertFalse(any(name.lower().startswith('sec-ch-') for name in headers))
        self.assertNotIn('Accept-Encoding', headers)

    def test_captured_hints_are_preserved_in_prepared_request(self):
        captured = {
            'Sec-CH-UA': '"Chromium";v="140", "Not=A?Brand";v="24"',
            'Sec-CH-UA-Platform': '"macOS"',
            'Sec-CH-UA-Mobile': '?0',
            'Sec-CH-UA-Full-Version-List': '"Chromium";v="140.0.7339.1"',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        environment = {
            'GLADOS_USER_AGENT': USER_AGENT,
            'GLADOS_BROWSER_HEADERS': json.dumps(captured),
        }
        with patch.dict(os.environ, environment, clear=True):
            headers = glados.build_headers()
        prepared = requests.Request('GET', glados.STATUS_URL, headers=headers).prepare()
        self.assertEqual(prepared.headers['User-Agent'], USER_AGENT)
        for name, value in captured.items():
            self.assertEqual(prepared.headers[name], value)

    def test_invalid_configuration_fails_before_network_without_echoing_values(self):
        invalid_environments = [
            {},
            {'GLADOS_USER_AGENT': ' '},
            {'GLADOS_USER_AGENT': ' private-ua'},
            {'GLADOS_USER_AGENT': 'private-ua\r\nCookie: private-cookie'},
            {'GLADOS_USER_AGENT': 'private-ua\tvalue'},
            {'GLADOS_USER_AGENT': 'private-ua\u4e2d'},
            {'GLADOS_BROWSER_HEADERS': 'private-invalid-json'},
            {'GLADOS_BROWSER_HEADERS': '[]'},
            {'GLADOS_BROWSER_HEADERS': 'null'},
            {'GLADOS_BROWSER_HEADERS': '{"sec-ch-ua": 123}'},
            {'GLADOS_BROWSER_HEADERS': '{"sec-ch-ua": null}'},
            {'GLADOS_BROWSER_HEADERS': '{"sec-ch-ua": ""}'},
            {'GLADOS_BROWSER_HEADERS': '{"sec-ch-ua": " private-value"}'},
            {'GLADOS_BROWSER_HEADERS': json.dumps({'sec-ch-ua': '\u00a0private-value'})},
            {'GLADOS_BROWSER_HEADERS': json.dumps({'sec-ch-ua': '\u0085private-value'})},
            {'GLADOS_BROWSER_HEADERS': '{"sec-ch-ua": "private-value\\nother"}'},
            {'GLADOS_BROWSER_HEADERS': '{"Cookie": "private-cookie"}'},
            {'GLADOS_BROWSER_HEADERS': '{"User-Agent": "private-override"}'},
            {'GLADOS_BROWSER_HEADERS': '{"Host": "private-host"}'},
            {'GLADOS_BROWSER_HEADERS': '{"Accept-Encoding": "private-encoding"}'},
        ]
        for invalid in invalid_environments:
            with self.subTest(invalid=invalid):
                environment = {'GLADOS_COOKIES': 'private-cookie'}
                if 'GLADOS_USER_AGENT' not in invalid and invalid:
                    environment['GLADOS_USER_AGENT'] = USER_AGENT
                environment.update(invalid)
                output = io.StringIO()
                with patch.dict(os.environ, environment, clear=True):
                    with patch.object(glados.requests, 'Session') as session_factory:
                        with patch.object(glados, 'push_message') as push:
                            with redirect_stdout(output):
                                self.assertEqual(glados.main(), 1)
                session_factory.assert_not_called()
                push.assert_not_called()
                self.assertIn('浏览器配置错误', output.getvalue())
                self.assertNotIn('private-', output.getvalue())

    def test_optional_blank_headers_are_accepted(self):
        for raw in ('', '  ', '{}'):
            with self.subTest(raw=raw):
                environment = {
                    'GLADOS_USER_AGENT': USER_AGENT,
                    'GLADOS_BROWSER_HEADERS': raw,
                }
                with patch.dict(os.environ, environment, clear=True):
                    self.assertEqual(glados.build_headers()['User-Agent'], USER_AGENT)

    def test_both_api_calls_get_configured_headers_without_logging_cookies(self):
        environment = {
            'GLADOS_COOKIES': 'private-cookie',
            'GLADOS_USER_AGENT': USER_AGENT,
            'GLADOS_BROWSER_HEADERS': '{"sec-ch-ua-platform": "\\"macOS\\""}',
        }
        session = Mock()
        session.get.return_value = Mock(
            status_code=200,
            json=Mock(return_value={
                'code': 0,
                'data': {'email': 'user@example.test', 'leftDays': '12.75'},
            }),
        )
        session.post.return_value = Mock(
            status_code=200,
            json=Mock(return_value={
                'code': 0,
                'list': [{'balance': '100', 'change': '1'}],
            }),
        )
        output = io.StringIO()
        with patch.dict(os.environ, environment, clear=True):
            with patch.object(glados.requests, 'Session') as session_factory:
                session_factory.return_value.__enter__.return_value = session
                with patch.object(glados, 'push_message'):
                    with redirect_stdout(output):
                        self.assertEqual(glados.main(), 0)
        for call in (session.get.call_args, session.post.call_args):
            self.assertEqual(call.kwargs['headers']['User-Agent'], USER_AGENT)
            self.assertEqual(call.kwargs['headers']['sec-ch-ua-platform'], '"macOS"')
            self.assertEqual(call.kwargs['headers']['Cookie'], 'private-cookie')
        self.assertNotIn('private-cookie', output.getvalue())
        self.assertIn('变化：1', output.getvalue())


if __name__ == '__main__':
    unittest.main()
