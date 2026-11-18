"""Run the site's own check-in flow in an isolated browser context."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
import re
from urllib.parse import urlsplit


@dataclass
class AccountResult:
    email: str = ''
    days: str = '未知'
    ok: bool = False
    message: str = ''
    submitted: bool = False
    unknown: bool = False


STATUS_SCRIPT = """async () => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
        const response = await fetch('/api/user/status', {
            credentials: 'same-origin', signal: controller.signal
        });
        let body;
        try {
            body = await response.json();
        } catch (_) {
            return {http: response.status, invalid: true};
        }
        if (!body || typeof body !== 'object' || Array.isArray(body)) {
            return {http: response.status, invalid: true};
        }
        return {
            http: response.status,
            code: body.code,
            email: body.data && body.data.email,
            leftDays: body.data && body.data.leftDays
        };
    } finally {
        clearTimeout(timer);
    }
}"""


def _zero(value):
    return type(value) in (int, float) and value == 0


def _number(value):
    """Only display numeric API fields, never arbitrary response strings."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return '未知'
    try:
        number = Decimal(str(value))
        if not number.is_finite():
            return '未知'
        return str(int(number))
    except (InvalidOperation, ValueError, OverflowError):
        return '未知'


def _cookies(raw, base_url):
    cookies = []
    names = set()
    for part in raw.split(';'):
        part = part.strip()
        if not part:
            continue
        name, separator, value = part.partition('=')
        if (
            not separator or not name or name != name.strip() or not value
            or name in names
            or any(ord(char) < 33 or ord(char) == 127 for char in name)
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError('Cookie 格式无效，请重新复制完整请求中的 Cookie')
        names.add(name)
        cookies.append({
            'name': name,
            'value': value,
            'url': base_url + '/',
            'secure': True,
        })
    if not {'gld:sess', 'gld:sess.sig'}.issubset(names):
        raise ValueError('Cookie 缺少新版登录会话字段，请重新登录并复制完整 Cookie')
    return cookies


class BrowserCheckin:
    def __init__(self, base_url, user_agent, extra_headers=None, headless=False,
                 channel='chrome', timeout=120):
        self.base_url = base_url.rstrip('/')
        if self.base_url not in {'https://glados.rocks', 'https://glados.cloud'}:
            raise ValueError('签到域名必须是 glados.rocks 或 glados.cloud 的 HTTPS 地址')
        self.user_agent = user_agent
        self.extra_headers = {
            name.lower(): value for name, value in (extra_headers or {}).items()
            if name.lower() == 'accept-language' or name.lower().startswith('sec-ch-')
        }
        self.headless = headless
        self.channel = channel
        self.timeout_ms = int(timeout * 1000)
        self.browser = None
        self._playwright = None
        self._owned_browser = False

    def __enter__(self):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError('缺少浏览器依赖，请执行 python -m pip install -r requirements.txt') from None
        try:
            self._playwright = sync_playwright().start()
            options = {'headless': self.headless, 'timeout': self.timeout_ms}
            if self.channel != 'chromium':
                options['channel'] = self.channel
            self.browser = self._playwright.chromium.launch(**options)
            self._owned_browser = True
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise RuntimeError('浏览器启动失败，请确认已安装所选 Chrome/Edge 或 Playwright Chromium') from None

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            if self._owned_browser and self.browser is not None:
                try:
                    self.browser.close()
                except Exception:
                    pass
        finally:
            self.browser = None
            self._owned_browser = False
            if self._playwright is not None:
                try:
                    self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None

    def _matches(self, request):
        url = urlsplit(request.url)
        return (
            url.scheme + '://' + url.netloc == self.base_url
            and url.path == '/api/user/checkin'
            and request.method == 'POST'
        )

    def _guard(self, route, state):
        request = route.request
        url = urlsplit(request.url)
        if (
            url.path == '/api/user/checkin/challenge' and request.method == 'GET'
            and url.scheme + '://' + url.netloc == self.base_url
        ):
            route.fallback()
            return
        if not self._matches(request):
            state['armed'] = False
            state['blocked'] = '签到请求目标不符合预期，未提交签到'
            route.abort()
            return
        if not state['armed'] or state['submitted']:
            if not state['submitted'] and not state['blocked']:
                state['blocked'] = '身份核对前出现签到请求，已阻止提交'
            route.abort()
            return
        try:
            payload = request.post_data_json
        except Exception:
            payload = None
        if (
            not isinstance(payload, dict)
            or payload.get('token') != urlsplit(self.base_url).hostname
            or not isinstance(payload.get('nonce'), str) or not payload['nonce']
            or not isinstance(payload.get('proof'), str) or not payload['proof']
            or payload.get('tsState') not in ('ok', 'off')
            or (payload.get('tsState') == 'ok' and (
                not isinstance(payload.get('turnstile'), str) or not payload['turnstile']
            ))
        ):
            state['armed'] = False
            state['blocked'] = '官网验证未完成或请求格式已变化，未提交签到；请在浏览器中完成验证'
            route.abort()
            return
        # Count the allowed attempt before handing it to the network. Any later
        # network/response failure is ambiguous and must never cause a retry.
        state['armed'] = False
        state['submitted'] = True
        route.fallback()

    def _status(self, page):
        status = page.evaluate(STATUS_SCRIPT)
        if not isinstance(status, dict):
            raise ValueError('状态响应格式无效 HTTP=未知 code=未知，未提交签到')
        http = status.get('http')
        code = status.get('code')
        http_label = http if type(http) is int and 100 <= http <= 599 else '未知'
        code_label = code if (
            type(code) is int or (type(code) is float and math.isfinite(code))
        ) else '未知'
        evidence = f'HTTP={http_label} code={code_label}'
        if type(http) is not int or http != 200:
            raise ValueError(f'状态查询失败 {evidence}，无法确认登录状态，未提交签到')
        if status.get('invalid') is True:
            raise ValueError(f'状态响应格式无效 {evidence}，未提交签到')
        if not _zero(code):
            if type(code) in (int, float) and code == -2:
                raise ValueError(f'status失败 {evidence} 登录会话未获授权，请更新当前域名对应的完整 Cookie')
            raise ValueError(f'状态查询失败 {evidence}，未提交签到')
        if (
            not isinstance(status.get('email'), str)
            or '@' not in status['email']
            or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in status['email'])
        ):
            raise ValueError(f'状态响应身份字段缺失或无效 {evidence}，未提交签到')
        return status

    @staticmethod
    def _response(result, response):
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError('Invalid response shape')
        if response.status != 200 or not _zero(body.get('code')):
            if body.get('reason') == 'turnstile':
                result.message = '签到失败：Cloudflare Turnstile 验证未通过，需要在浏览器中完成验证'
            elif body.get('reason') == 'device-mismatch':
                result.message = '签到失败：登录设备不匹配，请使用相同浏览器环境重新登录'
            else:
                code = body.get('code')
                code = code if type(code) in (int, float) else '未知'
                result.message = f'签到失败（HTTP {response.status}，业务码 {code}）'
            return result
        result.ok = True
        if body.get('repeated') is True:
            result.message = '今日已签到（服务端判定，未确认新增积分）'
            return result
        result.message = '签到成功'
        entries = body.get('list')
        if isinstance(entries, list) and entries and isinstance(entries[0], dict):
            result.message += '|积分：{}|接口记录变化：{}'.format(
                _number(entries[0].get('balance')), _number(entries[0].get('change')),
            )
        return result

    def checkin(self, cookie, expected_email=None, status_only=False):
        result = AccountResult()
        context = None
        state = {'armed': False, 'submitted': False, 'blocked': ''}
        try:
            cookies = _cookies(cookie, self.base_url)
            if self.browser is None:
                raise ValueError('浏览器尚未启动')
            context = self.browser.new_context(
                user_agent=self.user_agent,
                extra_http_headers=self.extra_headers,
                service_workers='block',
            )
            context.set_default_timeout(self.timeout_ms)
            context.add_cookies(cookies)
            context.route(re.compile(r'^https?://[^/]+/api/user/checkin'),
                          lambda route: self._guard(route, state))
            page = context.new_page()
            page.goto(self.base_url + '/console/checkin', wait_until='domcontentloaded')
            current = urlsplit(page.url)
            if current.scheme + '://' + current.netloc != self.base_url:
                raise ValueError('页面跳转到其他域名，已停止签到')
            status = self._status(page)
            if state['blocked']:
                raise ValueError('页面提前尝试提交签到，已停止本账号处理')
            result.email = status['email']
            result.days = _number(status.get('leftDays'))
            if expected_email is not None and result.email != expected_email:
                raise ValueError('浏览器账号与预期账号不一致，已停止签到')
            if status_only:
                result.ok = True
                result.message = '只读检查通过（未提交签到）'
                return result
            button = page.locator('button.ckb')
            button.wait_for(state='visible')
            if self._status(page)['email'] != result.email:
                raise ValueError('浏览器账号在提交前发生变化，已停止签到')
            state['armed'] = True
            # The response event only means headers arrived. Observe completion
            # before clicking too, so a stalled body is bounded by the same wait.
            with page.expect_event('requestfinished', predicate=self._matches,
                                   timeout=self.timeout_ms):
                with page.expect_response(lambda response: self._matches(response.request),
                                          timeout=self.timeout_ms) as captured:
                    button.click()
            result.submitted = state['submitted']
            if not result.submitted:
                raise ValueError('未观察到获准的签到请求')
            return self._response(result, captured.value)
        except ValueError as exc:
            result.message = state['blocked'] or str(exc)
            if state['submitted']:
                result.unknown = True
                result.message = '签到请求已提交，但响应无效或读取失败，结果未知；请核对官网记录，不自动重试'
            return result
        except Exception:
            result.unknown = state['submitted']
            result.message = state['blocked'] or (
                '签到请求已提交，但未获得明确响应，结果未知；请核对官网记录，不自动重试'
                if result.unknown else '浏览器页面或验证未能完成，未提交签到；请在浏览器中检查验证状态'
            )
            return result
        finally:
            result.submitted = state['submitted']
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass
