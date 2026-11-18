"""Run GLaDOS's official browser check-in flow for isolated accounts."""

import json
import os
import sys

import requests

from browser_checkin import BrowserCheckin


PUSHPLUS_URL = 'https://www.pushplus.plus/send'
TIMEOUT = 20
ALLOWED_ORIGINS = {'https://glados.rocks', 'https://glados.cloud'}
BROWSER_HEADER_NAMES = frozenset({
    'accept-language', 'sec-ch-ua', 'sec-ch-ua-mobile', 'sec-ch-ua-platform',
    'sec-ch-ua-full-version', 'sec-ch-ua-full-version-list',
    'sec-ch-ua-platform-version', 'sec-ch-ua-arch', 'sec-ch-ua-bitness',
    'sec-ch-ua-model', 'sec-ch-ua-wow64',
})


def validate_header_value(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('浏览器请求头必须是非空字符串')
    if value[0].isspace():
        raise ValueError('浏览器请求头不能以空白字符开头')
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError('浏览器请求头不能包含换行或控制字符')
    try:
        value.encode('latin-1')
    except UnicodeEncodeError:
        raise ValueError('浏览器请求头包含不支持的字符') from None


def get_base_url():
    base_url = os.environ.get('GLADOS_BASE_URL', 'https://glados.rocks').rstrip('/')
    if base_url not in ALLOWED_ORIGINS:
        raise ValueError('GLADOS_BASE_URL 仅支持 https://glados.rocks 或 https://glados.cloud')
    return base_url


def build_headers():
    user_agent = os.environ.get('GLADOS_USER_AGENT', '')
    if not user_agent.strip():
        raise ValueError('请设置 GLADOS_USER_AGENT，使用获取 Cookie 的浏览器的完整 User-Agent')
    validate_header_value(user_agent)
    base_url = get_base_url()
    headers = {
        'Referer': base_url + '/console/checkin', 'Origin': base_url,
        'User-Agent': user_agent.strip(), 'Accept': 'application/json, text/plain, */*',
        'Content-Type': 'application/json; charset=utf-8',
        'Sec-Fetch-Site': 'same-origin', 'Sec-Fetch-Mode': 'cors', 'Sec-Fetch-Dest': 'empty',
    }
    raw_headers = os.environ.get('GLADOS_BROWSER_HEADERS', '').strip()
    if raw_headers:
        try:
            browser_headers = json.loads(raw_headers)
        except ValueError:
            raise ValueError('GLADOS_BROWSER_HEADERS 必须是有效的 JSON 对象') from None
        if not isinstance(browser_headers, dict):
            raise ValueError('GLADOS_BROWSER_HEADERS 必须是 JSON 对象')
        for name, value in browser_headers.items():
            name = name.lower()
            if name not in BROWSER_HEADER_NAMES:
                raise ValueError('GLADOS_BROWSER_HEADERS 只允许 Client Hints 和 Accept-Language')
            validate_header_value(value)
            headers[name] = value
    return headers


def read_bool(name, default=False):
    value = os.environ.get(name, str(default)).lower()
    if value not in {'true', 'false', '1', '0'}:
        raise ValueError(f'{name} 必须为 true 或 false')
    return value in {'true', '1'}


def browser_options(headers):
    channel = os.environ.get('GLADOS_BROWSER_CHANNEL', 'chrome')
    if channel not in {'chrome', 'msedge', 'chromium'}:
        raise ValueError('GLADOS_BROWSER_CHANNEL 必须为 chrome、msedge 或 chromium')
    try:
        timeout = int(os.environ.get('GLADOS_BROWSER_TIMEOUT', '120'))
    except ValueError:
        raise ValueError('GLADOS_BROWSER_TIMEOUT 必须为 30 至 180 的整数秒数') from None
    if not 30 <= timeout <= 180:
        raise ValueError('GLADOS_BROWSER_TIMEOUT 必须为 30 至 180 的整数秒数')
    return {
        'base_url': get_base_url(), 'user_agent': headers['User-Agent'],
        'extra_headers': {name: value for name, value in headers.items()
                          if name.lower() in BROWSER_HEADER_NAMES},
        'headless': read_bool('GLADOS_HEADLESS'), 'channel': channel, 'timeout': timeout,
    }


def push_message(token, content):
    if not token or not content:
        return
    try:
        requests.get(PUSHPLUS_URL,
                     params={'token': token, 'title': 'GLaDOS签到情况', 'content': content},
                     timeout=TIMEOUT, allow_redirects=False)
    except requests.RequestException:
        # Exception text can include the token-bearing query string.
        print('PushPlus 推送失败，请检查网络与通知配置')


def main():
    cookies = [cookie.strip() for cookie in os.environ.get('GLADOS_COOKIES', '').split('&') if cookie.strip()]
    if not cookies:
        print('未获取到 GLADOS_COOKIES 环境变量')
        return 1
    try:
        options = browser_options(build_headers())
        status_only = read_bool('GLADOS_STATUS_ONLY')
    except ValueError as exc:
        print(f'浏览器配置错误：{exc}')
        return 1
    messages = []
    failed = False
    try:
        with BrowserCheckin(**options) as runner:
            for index, cookie in enumerate(cookies, 1):
                try:
                    result = runner.checkin(cookie, status_only=status_only)
                    account = result.email or f'Cookie{index}'
                    message = f'{account}|剩余：{result.days}天|{result.message}'
                    failed = failed or not result.ok
                except Exception:
                    # Preserve account isolation without logging credential-bearing exceptions.
                    message = f'Cookie{index}|执行失败；请核对浏览器环境，未自动重试'
                    failed = True
                print(message, flush=True)
                messages.append(message)
    except Exception:
        print('浏览器启动或运行失败；请安装 requirements.txt 和对应浏览器，并检查可用桌面环境')
        failed = True
    if not status_only:
        push_message(os.environ.get('PUSHPLUS_TOKEN', ''), '\n'.join(messages))
    return 1 if failed else 0


if __name__ == '__main__':
    for stream_name in ('stdout', 'stderr'):
        stream = getattr(sys, stream_name)
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    raise SystemExit(main())
