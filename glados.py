# -*- coding: utf-8 -*-
"""GLaDOS GitHub Actions 签到脚本。

GLADOS_COOKIES 使用 & 分隔多个完整 Cookie。脚本逐个账号处理，单个账号
失败不会阻断其它账号，并把服务端业务错误发送到 PushPlus。
"""

import json
import os
import sys
from urllib.parse import urlencode

import requests


CHECKIN_URL = 'https://glados.cloud/api/user/checkin'
STATUS_URL = 'https://glados.cloud/api/user/status'
PUSHPLUS_URL = 'https://www.pushplus.plus/send'
TIMEOUT = 20


def parse_json(response):
    try:
        return response.json()
    except ValueError:
        return {}


def status_account(session, headers):
    response = session.get(STATUS_URL, headers=headers, timeout=TIMEOUT)
    body = parse_json(response)
    if response.status_code != 200 or body.get('code') != 0 or not body.get('data'):
        raise RuntimeError(
            'status失败 HTTP={} code={} reason={} message={}'.format(
                response.status_code,
                body.get('code', '未知'),
                body.get('reason', ''),
                body.get('message', ''),
            )
        )
    data = body['data']
    return data.get('email', '未知账号'), str(data.get('leftDays', '未知')).split('.')[0]


def checkin_account(session, headers):
    response = session.post(
        CHECKIN_URL,
        headers=headers,
        json={'token': 'glados.cloud'},
        timeout=TIMEOUT,
    )
    body = parse_json(response)
    checkin_list = body.get('list') or []
    if checkin_list:
        item = checkin_list[0]
        return '{}|积分：{}|变化：{}'.format(
            body.get('message', '签到成功'),
            str(item.get('balance', '')).split('.')[0],
            str(item.get('change', '')).split('.')[0],
        )

    reason = body.get('message') or body.get('reason') or '未知错误'
    if body.get('reason') == 'device-mismatch':
        reason = '设备不匹配：登录设备={}，运行设备={}。请重新登录或更换 Runner。'.format(
            body.get('loginDevice', '未知'), body.get('currentDevice', '未知')
        )
    return '签到失败：{} (HTTP {} code {})'.format(
        reason, response.status_code, body.get('code', '未知')
    )


def push_message(token, content):
    if not token or not content:
        return
    try:
        requests.get(
            PUSHPLUS_URL,
            params={'token': token, 'title': 'GLaDOS签到情况', 'content': content},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        print('PushPlus 推送失败：{}'.format(exc))


def main():
    push_token = os.environ.get('PUSHPLUS_TOKEN', '')
    raw_cookies = os.environ.get('GLADOS_COOKIES', '')
    cookies = [item.strip() for item in raw_cookies.split('&') if item.strip()]
    if not cookies:
        print('未获取到 GLADOS_COOKIES 环境变量')
        return 0
    print('GitHub Runner OS: {}'.format(os.environ.get('RUNNER_OS', 'unknown')))

    base_headers = {
        'Referer': 'https://glados.cloud/console/checkin',
        'Origin': 'https://glados.cloud',
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        ),
        'Accept': 'application/json, text/plain, */*',
        'Content-Type': 'application/json; charset=utf-8',
    }

    messages = []
    with requests.Session() as session:
        for index, cookie in enumerate(cookies, 1):
            headers = dict(base_headers)
            headers['Cookie'] = cookie
            try:
                email, days = status_account(session, headers)
                result = checkin_account(session, headers)
                message = '{}|剩余：{}天|{}'.format(email, days, result)
            except requests.RequestException as exc:
                message = 'Cookie{}|网络请求失败：{}'.format(index, exc)
            except Exception as exc:
                message = 'Cookie{}|{}'.format(index, exc)
            print(message)
            messages.append(message)

    push_message(push_token, '\n'.join(messages))
    # 服务端业务失败已经被记录和推送，不让单个账号失败阻断整个 Action。
    return 0


if __name__ == '__main__':
    # Windows GitHub Runner 可能使用 cp1252，中文日志需切换到 UTF-8。
    for stream_name in ('stdout', 'stderr'):
        stream = getattr(sys, stream_name)
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    raise SystemExit(main())
