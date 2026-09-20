# 从自己的应用调用述影

**只想在手机上使用？** 用手机浏览器打开服务地址的首页（不要带 `/docs`），输入访问密钥，粘贴 B站 / YouTube 视频链接，或选择视频、录音、字幕即可。手机页面默认生成文字、AI 总结和思维导图，也可选择仅转文字。页面会自动更新进度，完成后通过“全文转写 / AI 总结 / 思维导图”切换查看，并可下载文稿。已有转写可以补生成总结和导图，无需重新转写。密钥仅在当前标签页保留，点“退出”会清除。以下接口说明供开发者接入自己的应用使用。

手机应用、脚本、网站后端和其他电脑都可以通过 HTTPS 上传材料、读取进度、取得文字和导出文档。服务在一台 Windows 电脑上处理任务，调用端不需要安装模型。服务安装见[部署指南](service.md)。

本功能目前随源码提供，桌面 Alpha.3 ZIP 不包含 API 服务安装脚本。

## 先跑通一次

向服务管理员取得 HTTPS 地址和 API 密钥。所有 `/v1/` 请求使用 `Authorization: Bearer <API_KEY>`；不要把密钥放在网址里。`/docs` 提供交互文档，`/openapi.json` 可用于生成客户端。

下面是 Bash 示例，环境变量由你在自己的设备上配置：

```bash
export SHUYING_URL='https://YOUR_API_HOST'
read -rs SHUYING_KEY

curl --fail-with-body "$SHUYING_URL/v1/jobs?filename=lesson.srt" \
  -H "Authorization: Bearer $SHUYING_KEY" \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @lesson.srt
```

返回 `202` 和任务 `id`。上传的是文件原始字节，不是 multipart 表单。文件名含中文或空格时应 URL 编码。音视频也采用相同方式上传。

```bash
JOB_ID='替换为返回的id'
curl --fail-with-body "$SHUYING_URL/v1/jobs/$JOB_ID" \
  -H "Authorization: Bearer $SHUYING_KEY"

# status 为 completed 后下载文字稿
curl --fail-with-body "$SHUYING_URL/v1/jobs/$JOB_ID/export?format=txt" \
  -H "Authorization: Bearer $SHUYING_KEY" -o transcript.txt
```

推荐每 30 秒查询一次进度，遇到 `429` 按 `Retry-After` 等待。任务状态为 `completed`、`failed` 或 `canceled` 后停止轮询。上传连接中断时，先查询任务列表，确认是否已创建任务，再决定是否重新上传。

## 接口

| 方法与路径 | 用途 |
| --- | --- |
| `GET /healthz` | 服务存活检查，不需要密钥 |
| `GET /v1/capabilities` | 查询实际文件、时长、队列和请求限额 |
| `POST /v1/jobs?filename=lesson.mp4` | 上传文件，默认用 GPU + 高精度 large-v3 转写；`mode=lecture` 加做笔记，`device=cpu` 可显式选择 CPU |
| `POST /v1/jobs/link` | JSON 请求体 `{"url":"视频链接"}`，创建链接任务；支持 B站、b23.tv 短链及 YouTube 单视频，也可粘贴分享文字 |
| `GET /v1/jobs?limit=20&offset=0` | 分页查询当前密钥的任务 |
| `GET /v1/jobs/{id}` | 读取状态和进度 |
| `GET /v1/jobs/{id}/result` | 取得独立的全文转写（segments）、摘要（summary）和主题导图（mindmap），以及兼容字段 blocks 和 glossary |
| `GET /v1/jobs/{id}/export?format=md` | 导出 `md`、`docx`、`txt`、`srt`、`vtt`、`json` 或 `outline` |
| `POST /v1/jobs/{id}/notes` | 已有文字生成笔记，JSON 请求体 `{"proofread":false}` |
| `POST /v1/jobs/{id}/cancel` | 取消任务 |
| `POST /v1/jobs/{id}/retry` | 重试失败或取消的任务 |
| `DELETE /v1/jobs/{id}` | 删除不再运行的任务及其文件 |

默认单个媒体最大 64 MiB、最长 30 分钟，字幕最大 10 MiB。支持 UTF-8 SRT/VTT，以及 MP4、MKV、WebM、MOV、MP3、WAV、M4A、FLAC。默认全服务最多保留 50 个任务、最多 4 个排队或处理中的任务，单工作进程按顺序处理；每个密钥每分钟最多 120 次请求。限额包含所有调用端，请及时删除不需要的材料。

公网接口接受文件和受限的视频链接：B站、YouTube 单个公开视频；频道、合集页、直播、需要登录或付费的内容不支持。短链接展开后仍会验证目标站点；分享参数会被清理，B站分P编号会保留。站点访问限制可能导致下载失败，此时可改为上传自己的文件。链接任务同样受 30 分钟和 64 MiB 下载限额约束。转写使用服务器上的语音模型，第一次使用可能需要下载模型，CPU 通常比 GPU 慢。笔记使用服务管理员配置的默认模型：可以是本机 Ollama，也可以是兼容的在线服务。在线模式会把整理所需的转写文字发送给配置的服务商，不发送音视频。桌面端的模型设置不会自动同步到独立 API 服务。

## Python 示例

安装 `httpx` 后使用：

```python
import os
import time
from pathlib import Path
import httpx

base = os.environ['SHUYING_URL'].rstrip('/')
headers = {'Authorization': 'Bearer ' + os.environ['SHUYING_KEY']}
with httpx.Client(base_url=base, headers=headers, timeout=150) as client:
    with Path('lesson.srt').open('rb') as source:
        response = client.post('/v1/jobs', params={'filename': 'lesson.srt'},
            headers={'Content-Type': 'application/octet-stream'}, content=source)
    response.raise_for_status()
    job_id = response.json()['id']
    while True:
        response = client.get(f'/v1/jobs/{job_id}')
        if response.status_code == 429:
            time.sleep(int(response.headers.get('Retry-After', '30')))
            continue
        response.raise_for_status()
        job = response.json()
        if job['status'] in {'completed', 'failed', 'canceled'}:
            break
        time.sleep(30)
    if job['status'] != 'completed':
        raise RuntimeError(job.get('error_code') or job['status'])
    response = client.get(f'/v1/jobs/{job_id}/export', params={'format': 'docx'})
    response.raise_for_status()
    Path('transcript.docx').write_bytes(response.content)
```

## 网页与错误处理

网页可以使用 `fetch`，将选中的 `File` 直接作为请求体，设置同样的认证和内容类型头。跨域网页需要管理员先允许该网页的明确 origin；原生应用、后端和命令行不受浏览器 CORS 限制。不要把共享密钥打包进公开网站的 JavaScript，应通过自己的后端调用，或让用户输入自己的密钥并仅保存在内存中。

不同密钥隔离任务；共用一个密钥的设备共用同一任务空间。访问其他密钥的任务与不存在的任务都返回 `404`。服务不会返回本机文件路径或原始异常信息。

错误通常采用 `{"error":{"code":"HTTP_401","message":"..."}}` 结构：`401` 密钥无效，`409` 状态不允许操作或存储任务已满，`413` 文件过大，`415` 上传内容类型不符，`422` 参数错误，`429` 队列或请求限流，`507` 磁盘不足。隧道或代理自身产生的错误可能采用其他格式。

电脑或服务重启后，未完成任务会标记为失败；客户端确认后调用 `retry`。服务不会自动重新执行这些任务。

### 三种结果

- `segments`：带时间点的全文转写。
- `summary`：每节包含 `heading`、核心结论 `takeaway` 和少量 `points`（`text`、`segment_ids`）。
- `mindmap`：每节包含中心主题 `topic`、概念分支 `branches`（`label`）、短关键词 `children`（`label`、`segment_ids`）。

摘要和导图分别生成，共用已有转写，不会再跑一次语音识别。导图大纲下载使用同一份主题树。旧任务或原文修改后缺少有效结果时，这两个字段返回空数组；调用笔记生成接口即可补齐，不会把原文当成摘要或导图。

手机首页与桌面本体共用可视化导图画布，支持拖动、缩放、分支折叠、适应画布和大画布模式；点击节点文字可回查转写。所有资源同源提供，无需 CDN。`mindmap` 数据格式保持不变，第三方客户端可以按同一主题树自行渲染。已有有效导图不需要再次调用模型。

任务失败或取消后，只要转写已保存，手机页面仍可阅读、导出文字，并可补生成总结和导图。`GET /v1/jobs/{id}/result` 同样可读取这些结果；仅当尚无转写时返回 409。任务的失败状态不会被已有结果掩盖。
