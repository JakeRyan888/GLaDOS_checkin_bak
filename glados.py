import datetime

import requests,os,json


if __name__ == '__main__':
#   pushplus token
    pkey = os.environ.get('PUSHPLUS_TOKEN','')
#   消息推送
    sendmsg = ''
#   GLaDOS cookie
    cookies = os.environ.get('GLADOS_COOKIES', '').split('&')
    if cookies[0] == '':
        print('未获取到GLADOS_COOKIES环境变量')
        cookies = []
        exit(0)
    checkin_url = 'https://glados.cloud/api/user/checkin'
    status_url = 'https://glados.cloud/api/user/status'
    referrer = 'https://glados.cloud/console/checkin'
    origin = 'https://glados.cloud'
    useragent = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    headers = {
        'Referer': referrer,
        'Origin': origin,
        'User-Agent': useragent,
        'Content-Type': 'application/json; charset=utf-8',
    }
    payload = {
        'token': 'glados.cloud'
    }
    for cookie in cookies:
        cookie = cookie.strip()
        if not cookie:
            continue
        request_headers = dict(headers)
        request_headers['Cookie'] = cookie

        checkin = requests.post(
            checkin_url, headers=request_headers, json=payload, timeout=20
        )
        status = requests.get(status_url, headers=request_headers, timeout=20)

        try:
            status_body = status.json()
        except ValueError:
            raise RuntimeError(
                'status 接口返回非 JSON：HTTP {}，响应前200字符：{}'.format(
                    status.status_code, status.text[:200]
                )
            )
        if status.status_code != 200 or status_body.get('code') != 0 or 'data' not in status_body:
            raise RuntimeError(
                'status 接口未认证或接口异常：HTTP {}，返回：{}'.format(
                    status.status_code, json.dumps(status_body, ensure_ascii=False)[:500]
                )
            )
        status_data = status_body['data']
        days = str(status_data.get('leftDays', '')).split('.')[0]
        email = status_data.get('email', '未知账号')

        try:
            checkin_body = checkin.json()
        except ValueError:
            checkin_body = {}
        checkin_list = checkin_body.get('list') or []
        if not checkin_list:
            raise RuntimeError(
                '签到接口异常：HTTP {}，返回：{}'.format(
                    checkin.status_code, json.dumps(checkin_body, ensure_ascii=False)[:500]
                )
            )
        balance = str(checkin_list[0].get('balance', '')).split('.')[0]
        change = str(checkin_list[0].get('change', '')).split('.')[0]

        if 'message' in checkin.text:
            msg = checkin.json()['message']
            print(email+'|'+'剩余：'+days+'天|'+msg+'|积分：'+balance+'|变化：'+ change +'\n')
            sendmsg += email+'|'+'剩余：'+days+'天|'+msg+'|积分：'+balance+'|变化：'+ change +'\n'
        else:
            sendmsg += email + '签到失败，请更新cookies'

    if pkey !='':
        requests.get( 'http://www.pushplus.plus/send?token=' + pkey + '&title=GLaDOS签到情况&content=' + sendmsg)
