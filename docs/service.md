# 在 Windows 电脑上运行 API

API 服务独立于桌面应用，使用单独的数据目录、任务队列和密钥。默认只监听 `127.0.0.1:8766`，通过 HTTPS 反向代理或隧道提供远程访问。不要把桌面端的 8765 端口直接暴露到公网。

## 安装

先按[开发指南](development.md)准备 Python 环境和转写运行时，再在仓库根目录运行：

```powershell
.\scripts\install_api_service.ps1
```

安装器复制服务代码与转写运行时到 `%LOCALAPPDATA%\ShuyingService`，限制该目录为当前 Windows 用户和 SYSTEM 可访问，并创建登录启动快捷方式。Python 虚拟环境仍引用仓库中的 `.venv`，不要移动或删除它。

安装目录中 `client-key.json` 保存初始调用密钥；`data/api-keys.json` 只保存验证摘要。不要把这两个文件、隧道配置或用户数据放进 Git 仓库。

这是**当前用户会话中的后台服务**：进程退出后守护程序会重新启动，Windows 登录后自动运行；尚不支持无人登录时自动启动。电脑关机、睡眠、退出登录或断网时，外部无法访问。持续提供服务需要保持电脑供电、联网并登录；若要求重启后无需登录即可恢复，应由管理员另行部署 Windows 服务或启动任务。

## 无自有域名的 HTTPS 入口

可以使用 [ngrok 官方 Windows 客户端](https://ngrok.com/download/windows)。将验证来源后的 `ngrok.exe` 放到安装目录的 `tools` 子目录。登录自己的 ngrok 账号，在控制台取得 personal authtoken，然后运行：

```powershell
.\scripts\connect_api_ngrok.ps1
```

连接脚本会在当前 Windows 会话中检查安装；配置不存在时先安装 API，ngrok 缺失时从官方来源下载并检查数字签名，然后才提示输入令牌。安装目录可以通过 `-InstallDir` 指定。

按提示在本机隐藏输入令牌。令牌仅保存在受限安装目录的 `ngrok.yml` 中，不作为进程命令行参数。脚本更新服务代码并重启守护程序，禁用请求内容检查和远程管理。默认使用账号获分配的开发域名，HTTPS 证书由 ngrok 提供。

从本机查看实际入口：

```powershell
(Invoke-RestMethod http://127.0.0.1:4040/api/tunnels).tunnels.public_url
```

在安装服务的同一个 Windows 终端、仓库根目录运行验收脚本：

```powershell
.\.venv\Scripts\python.exe .\scripts\verify_api_service.py
```

它读取本机密钥但不显示密钥，验证 HTTPS、认证、测试字幕处理与七种导出，再删除自己创建的测试任务。使用自定义安装位置时加 `--install-dir <目录>`。只有全部检查通过，才代表带认证的端到端调用已验证。

ngrok 免费计划目前提供一个自动分配的开发域名，端点没有运行时长超时，但有每月 1 GB 出站流量、20,000 次 HTTP 请求等限额；超额会影响可用性。以[官方当前限制](https://ngrok.com/docs/pricing-limits/free-plan-limits)为准。固定域名不等于可用性保证，账号及套餐规则可能变化。API 请求经过 ngrok，TLS 在其入口终止，请将它作为数据处理链路的一部分评估。

## 密钥与网页接入

以下命令在仓库根目录运行；输出文件应留在受限服务目录。不要同时运行多个密钥管理命令。

```powershell
$serviceRoot = Join-Path $env:LOCALAPPDATA 'ShuyingService'
$env:PYTHONPATH = Join-Path $serviceRoot 'app\backend'
.\.venv\Scripts\python.exe -m videosummarizer.service_host create-key `
  --data-dir "$serviceRoot\data" --output "$serviceRoot\another-client.json"
```

每个新密钥有独立任务空间。轮换时加 `--key-id <原有ID>` 并选择新的输出文件，旧令牌立即失效，任务归属保留。撤销：

```powershell
.\.venv\Scripts\python.exe -m videosummarizer.service_host revoke-key `
  --data-dir "$serviceRoot\data" --key-id '<要撤销的ID>'
```

服务每次认证都会重新读取注册表，不需要重启即可撤销。密钥允许上传、处理、导出和删除对应任务，应按使用者分配。

允许网页跨域访问时，停止服务，将 `service-runtime.json` 的 `origins` 设置为明确的来源数组，例如 `["https://your-app.example"]`，再启动。不要使用 `*`。服务端模型设置独立保存在 `data/llm_settings.json`；默认笔记模型与项目默认值相同，需要本机 Ollama 可用。

## 停止、启动与更新

在安装目录创建空文件 `STOP`，守护程序会在数秒内停止 API 和隧道。确认 8766 端口已停止监听，再备份、更新代码或移动文件。停止前先等待任务结束，强制停止会中断正在运行的任务。

重新启动时删除 `STOP`，运行 Windows 启动文件夹中的 `Shuying API` 快捷方式。不要同时运行多个服务实例；安装程序不会覆盖既有安装。

更新时保留 `data`、`client-key.json`、`ngrok.yml` 和 `service-runtime.json`，在停止状态下更新安装目录的 `app/backend/videosummarizer` 与 `service_supervisor.py`。仓库的代码修改不会自动改变已安装服务。

日志位于 `supervisor.log` 和 `data/api-service.log`，自动轮换。任务失败后查看本机日志；分享日志前检查并删除私人材料与路径。备份时先停止服务，备份整个数据目录。任务不会按时间自动删除，可通过 API 主动清理已完成材料。
