# GLaDOS_checkin_bak

通过系统 Chrome 打开 GLaDOS 官网签到页面，由官网获取新的 challenge、计算 proof，并运行官方 Turnstile 组件。脚本等待这套流程的结果，再读取签到接口响应；无需手动复制 `nonce`、`proof` 或 Turnstile 令牌。

**这不保证无人值守通过验证。** Cloudflare 明确将 Playwright 等自动化浏览器列为不支持解决生产 challenge 的环境。官方组件可能自动完成，也可能要求人工操作或拒绝当前环境；GitHub Actions 的机房网络同样可能被拒绝。脚本不会使用打码服务、隐身插件或伪造验证令牌。[Cloudflare 支持的浏览器说明](https://developers.cloudflare.com/cloudflare-challenges/reference/supported-browsers/)

## 签到行为

- 每个账号使用独立、临时的浏览器上下文；Cookie 仅注入所选 GLaDOS 域名，不复用个人浏览器资料目录。
- 提交前读取 `/api/user/status` 核对登录身份。登录失败或身份变化时停止该账号，继续处理后续账号。
- 只点击官网签到按钮一次，每个账号最多放行一次签到 POST。页面生成所需验证值，脚本不重放抓包中的旧值。
- 验证未完成时提示需要人工处理；已经提交但响应超时或无法解析时标记“结果未知”，不自动重试。
- 成功以接口 HTTP 状态和业务码为准，历史积分列表、按钮颜色和“已完成”样式都不作为新签到成功的证据。重复签到不宣称新增积分。
- 汇总结果可发送到 PushPlus。部分账号失败不会中止后续账号；本次有失败或未知结果时，进程返回非零状态。

## 配置 Secrets

在仓库 **Settings → Secrets and variables → Actions → Secrets** 中添加：

| Secret | 必填 | 内容 |
| --- | --- | --- |
| `GLADOS_COOKIES` | 是 | 每个账号的完整 Cookie，多个账号使用英文 `&` 分隔；各组应包含 `gld:sess` 和 `gld:sess.sig`。 |
| `GLADOS_USER_AGENT` | 是 | 获取上述 Cookie 的浏览器的完整 User-Agent。运行机器上的 Chrome 版本应与该浏览器一致。 |
| `GLADOS_BROWSER_HEADERS` | 否 | 同一浏览器请求中的 Client Hints 和 Accept-Language，格式为 JSON 对象。 |
| `PUSHPLUS_TOKEN` | 否 | PushPlus Token。 |

所有账号共用这一套 UA 和浏览器头，同批 Cookie 应来自相同的浏览器环境。浏览器升级、重新登录并更换 Cookie 时，同步更新这些配置。Cookie、Token 和抓包验证值不要写入仓库、Issue 或日志。

### 获取请求头

1. 使用登录 GLaDOS 的浏览器打开 `https://glados.rocks/console/checkin`。如果实际使用 `glados.cloud`，后续将 `GLADOS_BASE_URL` 设置为该域名。
2. 按 `F12` 打开 **Network**，刷新页面，选择一次成功的 `/api/user/status` 请求。
3. 把 **Request Headers** 的完整 `Cookie` 和 `User-Agent` 分别保存到对应 Secret。也可以在同一浏览器查看 `chrome://version` 中的用户代理。
4. 可选：把实际存在的 `sec-ch-ua`、`sec-ch-ua-mobile`、`sec-ch-ua-platform` 和 `accept-language` 组成 JSON，保存为 `GLADOS_BROWSER_HEADERS`。

下面只展示 JSON 结构，提示文字必须换成实际值，平台和语言也以自己的请求为准：

```json
{
  "sec-ch-ua": "替换为完整请求值，内部双引号需要转义",
  "sec-ch-ua-mobile": "?0",
  "sec-ch-ua-platform": "\"Windows\"",
  "accept-language": "zh-CN,zh;q=0.9"
}
```

请求值 `"Windows"` 对应 JSON 字符串 `"\"Windows\""`。没有发送的字段直接省略。还支持原请求中的 `sec-ch-ua-full-version`、`sec-ch-ua-full-version-list`、`sec-ch-ua-platform-version`、`sec-ch-ua-arch`、`sec-ch-ua-bitness`、`sec-ch-ua-model` 和 `sec-ch-ua-wow64`。

不要把 `Cookie`、`Origin`、`Referer`、`Content-Length`、HTTP/2 伪头或整个抓包请求放进这个 JSON。浏览器管理这些请求头；认证 Cookie 通过限定域名的 Cookie jar 提供，不作为全局请求头发送给第三方验证站点。

## 可选运行设置

在仓库同一页面的 **Variables** 中配置，或本地设置同名环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `GLADOS_BASE_URL` | `https://glados.rocks` | 仅接受 `https://glados.rocks` 或 `https://glados.cloud`；应与获取 Cookie 的域名一致。 |
| `GLADOS_BROWSER_CHANNEL` | `chrome` | 可选 `chrome`、`msedge`、`chromium`。前两者使用已安装的系统浏览器。 |
| `GLADOS_HEADLESS` | `false` | 默认显示浏览器窗口；设为 `true` 可隐藏窗口，但可能被验证拒绝。 |
| `GLADOS_BROWSER_TIMEOUT` | `120` | 单个浏览器操作的等待秒数，范围 30–180；账号流程可能包含多个操作。 |
| `GLADOS_STATUS_ONLY` | `false` | 设为 `true` 时仅打开浏览器检查登录状态，不点击签到、不提交签到请求，也不发送 PushPlus 通知。 |

Linux 的有界面模式需要可用显示环境；没有桌面时需自行提供显示环境或使用 headless 模式。推荐先在自己的电脑上使用与 Cookie/UA 一致的系统 Chrome 验证配置。

## 本地运行

安装 Python 3.11 和 Chrome。在项目目录打开 PowerShell：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

$env:GLADOS_COOKIES = '第一组完整Cookie&第二组完整Cookie'
$env:GLADOS_USER_AGENT = '获取这些Cookie的浏览器的完整User-Agent'
$env:GLADOS_BASE_URL = 'https://glados.rocks'
$env:GLADOS_STATUS_ONLY = 'true'
.\.venv\Scripts\python.exe glados.py
```

只读检查确认账号后，将 `$env:GLADOS_STATUS_ONLY = 'false'`，再运行同一命令进行一次签到。运行时保留浏览器窗口，遇到人工验证提示时在官网页面处理；脚本不会自动点击验证码。

选择 `chromium` 时先安装对应浏览器：

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
$env:GLADOS_BROWSER_CHANNEL = 'chromium'
```

## GitHub Actions

实际工作流是 `.github/workflows/main.yml`；根目录的 `config.yml` 仅为配置示例。工作流使用 Python 3.11、安装依赖并运行离线测试，然后启动 Windows 镜像自带的 Chrome。选择 `chromium` 时会额外安装 Playwright 的 Chromium。工作流不会覆盖安装系统 Chrome。

在 **Actions → GLaDOS 每日签到 → Run workflow** 中可勾选 `status_only`，只检查登录状态。未勾选时使用仓库变量 `GLADOS_STATUS_ONLY`，其默认值为 `false`。定时任务仍按实际 workflow 中的 cron 运行；推送代码本身不会触发签到。

**Actions 中浏览器能启动，不代表 Turnstile 一定放行。** 如果要求人工交互或返回验证失败，请在官网完成验证；不要把失败当作 Cookie 必然过期，也不要将抓到的短效令牌作为长期 Secret。

## 验证范围

离线测试验证账号隔离、Cookie 域名范围、身份检查、请求次数限制和成功/失败/未知结果的处理；它们不调用生产验证码，也不证明 Cloudflare 已放行。真实成功只能由本次官网签到响应和积分记录核对；超时后的积分记录也不能自动归因于刚才那次请求。

参考：[Playwright 浏览器与系统 Chrome](https://playwright.dev/python/docs/browsers)、[Playwright BrowserContext](https://playwright.dev/python/docs/api/class-browsercontext)、[Cloudflare 官方组件流程](https://developers.cloudflare.com/turnstile/get-started/client-side-rendering/)、[Turnstile 令牌校验与时效](https://developers.cloudflare.com/turnstile/get-started/server-side-validation/)。
