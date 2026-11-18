# GLaDOS_checkin_bak

GLaDOS GitHub Actions 签到脚本，支持多个 Cookie 和可选的 PushPlus 通知。

## 配置 Secrets

在 GitHub 仓库的 **Settings → Secrets and variables → Actions → New repository secret** 中配置：

| Secret | 必填 | 内容 |
| --- | --- | --- |
| `GLADOS_COOKIES` | 是 | 完整 Cookie；多个账号使用 `&` 分隔。 |
| `GLADOS_USER_AGENT` | 是 | 获取上述 Cookie 的浏览器的完整 User-Agent。 |
| `GLADOS_BROWSER_HEADERS` | 否 | 从同一浏览器复制的 Client Hints 和 Accept-Language，格式为 JSON 对象。 |
| `PUSHPLUS_TOKEN` | 否 | PushPlus Token。 |

脚本不再使用固定的 Chrome 120 UA。已配置 Cookie、但缺少或填错浏览器配置时，会在发出请求前失败并提示修正；日志不会打印浏览器配置的原始值。

## 获取浏览器请求头

1. 使用取得 Cookie 的浏览器打开 `https://glados.cloud/console/checkin`。
2. 在开发者工具 **Network** 中查看发往 `glados.cloud` 的 `/api/user/status` 或 `/api/user/checkin` 请求。
3. 将 **Request Headers** 中的 `User-Agent` 完整复制到 `GLADOS_USER_AGENT`。也可以在该浏览器控制台查看 `navigator.userAgent`。
4. 若请求里存在 `sec-ch-ua`、`sec-ch-ua-mobile`、`sec-ch-ua-platform`、`accept-language`，原样复制其值并组成 JSON，保存为 `GLADOS_BROWSER_HEADERS`。

下面仅展示 JSON 结构，`sec-ch-ua` 的提示文字必须替换为实际抓取值；平台和语言也应以你的浏览器为准：

```json
{
  "sec-ch-ua": "替换为请求中完整的 sec-ch-ua 值，内部双引号需要转义",
  "sec-ch-ua-mobile": "?0",
  "sec-ch-ua-platform": "\"Windows\"",
  "accept-language": "zh-CN,zh;q=0.9"
}
```

例如，浏览器值 `"Windows"` 对应 JSON 字符串 `"\"Windows\""`。macOS 浏览器应复制它自己的平台值。没有发送的头可以省略，不能用 Windows 示例补给其他平台。Firefox、Safari 等浏览器不必填写 Chromium 专用头。

还支持原请求中的 `sec-ch-ua-full-version`、`sec-ch-ua-full-version-list`、`sec-ch-ua-platform-version`、`sec-ch-ua-arch`、`sec-ch-ua-bitness`、`sec-ch-ua-model`、`sec-ch-ua-wow64`。除这些 Client Hints 和 `accept-language` 以外的字段会被拒绝；不要把整个抓包请求、Cookie 或 Token 填进这个 JSON。

所有账号共用这套 UA 和浏览器头；同一批 Cookie 应来自相同浏览器环境。浏览器更新、重新登录并更换 Cookie 时，同时更新这些 Secrets。

## 运行与验证

实际工作流是 `.github/workflows/main.yml`，根目录的 `config.yml` 仅为配置示例。两者都已接入新的 Secrets，并在签到前执行离线测试。

配置后，在仓库 **Actions → GLaDOS 每日签到 → Run workflow** 手动运行一次，查看日志中的 `积分` 和 `变化`；它们始终来自服务端返回值。单个账号请求或业务失败仍会记录并汇总通知，不会阻止后续账号处理。

本地离线测试（需 Python 3.9+）：

```sh
python -m pip install requests
python -m unittest discover -s tests -v
```

## 请求一致性的范围

脚本读取真实 UA，加入同源 API fetch 对应的 `Sec-Fetch-Site: same-origin`、`Sec-Fetch-Mode: cors`、`Sec-Fetch-Dest: empty`，并原样采用配置的 Client Hints；不会猜测品牌列表或主版本。

`Accept-Encoding` 由 Requests 根据实际解码能力生成，避免声明不支持的 Brotli 编码。HTTP 请求头一致不能复制浏览器的 TLS、HTTP/2、JavaScript 状态或网络出口，也不能保证恢复 10 分。关于“2026 年 10 月风控调整”和“修改 UA 即可恢复”的说法，本仓库未作验证。

参考：[Chrome UA Client Hints](https://developer.chrome.com/docs/privacy-security/user-agent-client-hints)、[MDN Fetch Metadata 示例](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Sec-Fetch-Site)、[Requests 自定义请求头](https://requests.readthedocs.io/en/latest/user/quickstart/#custom-headers)。
