import datetime

import requests,os,json


if __name__ == '__main__':
#   pushplus token
    pkey = os.environ.get('PUSHPLUS_TOKEN','')
#   消息推送
    sendmsg = ''
#   GLaDOS cookie
    cookies = os.environ.get('GLADOS_COOKIES',[]).split('&')
    if cookies[0] == '':
        print('未获取到GLADOS_COOKIES环境变量')
        cookies = []
        exit(0)
    checkin_url = 'https://glados.rocks/api/user/checkin'
    status_url = 'https://glados.rocks/api/user/status'
    referrer = 'https://glados.rocks/console/checkin'
    origin = 'https://glados.rocks'
    useragent = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    payload = {
        'token': 'glados.one'
    }

    for cookie in cookies:
        checkin = requests.post(checkin_url,
                                headers={'cookie':cookie,'referrer':referrer,'origin':origin,'user-agent':useragent,'content-type':'application/json; charset=utf-8'},data = json.dumps(payload))
        status = requests.get(status_url,headers={'cookie':cookie,'referrer':referrer,'origin':origin,'useragent':useragent})
        days = status.json()['data']['leftDays'].split('.')[0]
        email = status.json()['data']['email']

        balance = checkin.json()['list'][0]['balance'].split('.')[0]
        change = checkin.json()['list'][0]['change'].split('.')[0]

        if 'message' in checkin.text:
            msg = checkin.json()['message']
            print(email+'|'+'剩余：'+days+'天|'+msg+'|积分：'+balance+'|变化：'+ change +'\n')
            sendmsg += email+'|'+'剩余：'+days+'天|'+msg+'|积分：'+balance+'|变化：'+ change +'\n'
        else:
            sendmsg += email + '签到失败，请更新cookies'

    if pkey !='':
        requests.get( 'http://www.pushplus.plus/send?token=' + pkey + '&title=GLaDOS签到情况&content=' + sendmsg)








