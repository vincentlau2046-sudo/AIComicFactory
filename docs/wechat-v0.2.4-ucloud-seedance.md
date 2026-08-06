# Seedance 2.0 API 个人也能用了：通过 UCloud 曲线调用，附完整接入指南

> 火山引擎至今没对个人开发者开放 Seedance 2.0 API。但现在有一条路走通了。

## 背景

Seedance 2.0 发布后，不少人第一时间去火山引擎申请 API 权限，结果发现——**个人开发者根本申请不到**。企业认证、审核流程、配额限制，把大部分独立开发者挡在了门外。

但 Seedance 2.0 的多参考图模式实在太香了：丢进去几张角色参考图，模型就能生成保持角色一致性的视频，这对 AI 漫画、AI 短剧来说几乎是刚需。

好消息是：**UCloud ModelVerse 平台已经上线了 Seedance 2.0 的 API 服务，个人开发者可以直接注册使用，无需企业认证。**

AIComicBuilder 在本次更新中完成了对 UCloud Seedance 协议的适配，首尾帧模式、参考图模式、Seedance 2.0 多参考图模式全部打通。

![UCloud Seedance 2.0 配置界面](https://cdn.jsdelivr.net/gh/twwch/images/AIComicBuilder/images/2026/04/ucloud-seedance2.png)

## 配置方法

### 第一步：获取 UCloud API Key

1. 注册 UCloud 账号：https://astraflow.ucloud.cn
2. 进入 ModelVerse 控制台，开通 Seedance 模型服务
3. 在 API 管理中创建并复制你的 API Key

### 第二步：在 AIComicBuilder 中配置

1. 打开 AIComicBuilder → 右上角「设置」
2. 点击「添加供应商」，能力类型选择「视频」
3. 协议选择 **Seedance (UCloud)**
4. Base URL 会自动填充为 `https://api.modelverse.cn`（通常无需修改）
5. 填入你的 API Key
6. 点击「获取模型列表」，会出现以下两个模型：
   - **Seedance 1.5 Pro** (`doubao-seedance-1-5-pro-251215`)
   - **Seedance 2.0** (`doubao-seedance-2-0-260128`)
7. 勾选你需要使用的模型
8. 在项目编辑页面的视频模型选择器中切换到该供应商即可

![Seedance 2.0 生成结果](https://cdn.jsdelivr.net/gh/twwch/images/AIComicBuilder/images/2026/04/seedance2-result.png)

![UCloud Seedance 2.0 运行日志](https://cdn.jsdelivr.net/gh/twwch/images/AIComicBuilder/images/2026/04/ucloud-sd2-logs.png)

可以看到日志中 `model=doubao-seedance-2-0-260128`，3 张参考图，`duration=10`，任务提交后持续轮询直到生成完成，实测跑通无问题。

## UCloud Seedance API 格式说明

如果你是开发者，想了解底层调用方式，以下是 UCloud ModelVerse 的 Seedance API 格式：

### 提交任务

```
POST https://api.modelverse.cn/v1/tasks/submit
```

**Headers：**

```
Content-Type: application/json
Authorization: <YOUR_API_KEY>
```

**请求体（图生视频 - 首尾帧模式）：**

```json
{
  "model": "doubao-seedance-1-5-pro-251215",
  "input": {
    "content": [
      {
        "type": "text",
        "text": "让角色跑起来"
      },
      {
        "type": "image_url",
        "image_url": { "url": "data:image/png;base64,..." },
        "role": "first_frame"
      },
      {
        "type": "image_url",
        "image_url": { "url": "data:image/png;base64,..." },
        "role": "last_frame"
      }
    ]
  },
  "parameters": {
    "duration": 5,
    "ratio": "16:9",
    "resolution": "720p",
    "watermark": false,
    "generate_audio": false
  }
}
```

**请求体（参考图模式 - 单图）：**

```json
{
  "model": "doubao-seedance-1-5-pro-251215",
  "input": {
    "content": [
      {
        "type": "text",
        "text": "角色转头微笑"
      },
      {
        "type": "image_url",
        "image_url": { "url": "https://example.com/ref.png" },
        "role": "first_frame"
      }
    ]
  },
  "parameters": {
    "duration": 5,
    "ratio": "16:9",
    "resolution": "720p",
    "watermark": false
  }
}
```

**请求体（Seedance 2.0 多参考图模式）：**

```json
{
  "model": "doubao-seedance-2-0-260128",
  "input": {
    "content": [
      {
        "type": "text",
        "text": "两个角色在公园散步"
      },
      {
        "type": "image_url",
        "image_url": { "url": "https://example.com/char1.png" },
        "role": "reference_image"
      },
      {
        "type": "image_url",
        "image_url": { "url": "https://example.com/char2.png" },
        "role": "reference_image"
      }
    ]
  },
  "parameters": {
    "duration": 5,
    "ratio": "16:9",
    "resolution": "720p",
    "watermark": false,
    "generate_audio": true
  }
}
```

**响应：**

```json
{
  "output": {
    "task_id": "abc123"
  },
  "request_id": "req_xxx"
}
```

### 查询任务状态

```
GET https://api.modelverse.cn/v1/tasks/status?task_id=abc123
Authorization: <YOUR_API_KEY>
```

**响应（成功）：**

```json
{
  "output": {
    "task_id": "abc123",
    "task_status": "Success",
    "urls": ["https://xxx.ufileos.com/output.mp4"],
    "submit_time": 1768460826,
    "finish_time": 1768460932
  },
  "usage": {
    "completion_tokens": 108900,
    "total_tokens": 108900,
    "duration": 5
  }
}
```

**任务状态值：**

| 状态 | 含义 |
|------|------|
| `Pending` | 排队中 |
| `Running` | 生成中 |
| `Success` | 生成成功，`urls` 中包含视频下载链接 |
| `Failure` | 生成失败，查看 `error_message` |
| `Expired` | 任务超时过期 |

### 与火山引擎 Seedance API 的主要区别

| | 火山引擎 | UCloud ModelVerse |
|---|---|---|
| 提交接口 | `POST /api/v3/contents/generations/tasks` | `POST /v1/tasks/submit` |
| 轮询接口 | `GET /api/v3/contents/generations/tasks/{id}` | `GET /v1/tasks/status?task_id={id}` |
| 请求结构 | `{ model, content: [...] }` | `{ model, input: { content: [...] }, parameters: {...} }` |
| 参数位置 | 与 content 同级 | 在 `parameters` 对象内 |
| 成功状态 | `succeeded` | `Success` |
| 视频地址 | `content.video_url` | `output.urls[]` |
| 认证方式 | `Bearer <key>` | 直接传 `<key>`（无 Bearer 前缀） |

### parameters 参数说明

| 参数 | 类型 | 说明 |
|------|------|------|
| `duration` | int | 视频时长，4-12 秒，默认 5 |
| `ratio` | string | 宽高比：`16:9` / `4:3` / `1:1` / `3:4` / `9:16` / `21:9` / `adaptive` |
| `resolution` | string | 分辨率：`480p` / `720p` / `1080p`，默认 720p |
| `generate_audio` | boolean | 是否生成同步音频，默认 false |
| `watermark` | boolean | 是否包含水印，默认 false |
| `draft` | boolean | 样片模式（低消耗快速预览），默认 false |
| `camera_fixed` | boolean | 是否固定摄像头，默认 false |
| `seed` | int | 随机种子，范围 0-2147483647 |

---

## 新增通义万相（Wan）视频生成

除了 UCloud Seedance，本次更新同时接入了阿里云通义万相（DashScope）的视频生成 API，支持 Wan 2.6 和 Wan 2.7 全系列模型。

![Wan 通义万相配置界面](https://cdn.jsdelivr.net/gh/twwch/images/AIComicBuilder/images/2026/04/wan.png)

### 支持的模型

| 模型 ID | 说明 |
|---------|------|
| `wan2.7-t2v` | Wan 2.7 文生视频 |
| `wan2.7-r2v` | Wan 2.7 参考图/首尾帧生视频 |
| `wan2.6-t2v` | Wan 2.6 文生视频 |
| `wan2.6-i2v-flash` | Wan 2.6 图生视频 Flash |
| `wan2.6-i2v` | Wan 2.6 图生视频 |
| `wan2.6-r2v` | Wan 2.6 参考图生视频 |
| `wan2.6-r2v-flash` | Wan 2.6 参考图生视频 Flash |

### 配置方法

1. 获取阿里云 DashScope API Key：https://dashscope.console.aliyun.com
2. 打开 AIComicBuilder → 设置 → 添加供应商 → 能力类型选择「视频」
3. 协议选择 **Wan (通义万相)**
4. Base URL 自动填充为 `https://dashscope.aliyuncs.com/api/v1`
5. 填入 DashScope API Key
6. 获取模型列表 → 勾选需要的模型

### Wan API 格式说明

#### 提交任务

```
POST https://dashscope.aliyuncs.com/api/v1/services/aigc/video-generation/video-synthesis
```

**Headers：**

```
Content-Type: application/json
Authorization: Bearer <YOUR_API_KEY>
X-DashScope-Async: enable
```

**请求体（文生视频 - wan2.7）：**

```json
{
  "model": "wan2.7-t2v",
  "input": {
    "prompt": "一只猫在花园里奔跑"
  },
  "parameters": {
    "resolution": "720P",
    "ratio": "16:9",
    "duration": 5
  }
}
```

**请求体（首尾帧模式 - wan2.7）：**

```json
{
  "model": "wan2.7-r2v",
  "input": {
    "prompt": "角色从站立到跑步",
    "media": [
      { "type": "first_frame", "url": "data:image/png;base64,..." },
      { "type": "last_frame", "url": "data:image/png;base64,..." }
    ]
  },
  "parameters": {
    "resolution": "720P",
    "ratio": "16:9",
    "duration": 5
  }
}
```

**请求体（多参考图模式 - wan2.7）：**

```json
{
  "model": "wan2.7-r2v",
  "input": {
    "prompt": "两个角色在街头对话",
    "media": [
      { "type": "reference_image", "url": "https://example.com/char1.png" },
      { "type": "reference_image", "url": "https://example.com/char2.png" }
    ]
  },
  "parameters": {
    "resolution": "720P",
    "ratio": "16:9",
    "duration": 5
  }
}
```

**请求体（图生视频 - wan2.6）：**

```json
{
  "model": "wan2.6-i2v",
  "input": {
    "prompt": "角色挥手",
    "img_url": "data:image/png;base64,..."
  },
  "parameters": {
    "size": "1280*720",
    "duration": 5
  }
}
```

**响应：**

```json
{
  "output": {
    "task_id": "abc123"
  }
}
```

#### 查询任务状态

```
GET https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}
Authorization: Bearer <YOUR_API_KEY>
```

**响应（成功）：**

```json
{
  "output": {
    "task_id": "abc123",
    "task_status": "SUCCEEDED",
    "video_url": "https://xxx.oss.aliyuncs.com/output.mp4"
  }
}
```

**任务状态值：**

| 状态 | 含义 |
|------|------|
| `PENDING` | 排队中 |
| `RUNNING` | 生成中 |
| `SUCCEEDED` | 生成成功，`video_url` 包含下载链接 |
| `FAILED` | 生成失败，查看 `message` |

### Wan 2.7 vs 2.6 API 差异

| | Wan 2.7 | Wan 2.6 |
|---|---|---|
| 图片输入 | `media` 数组，支持多图 | `img_url` 单图字段 |
| 分辨率 | `resolution: "720P"` | `size: "1280*720"` |
| 宽高比 | `ratio: "16:9"` | 通过 size 控制（如 `720*1280`） |
| 参考图/首尾帧 | `media[].type` 区分角色 | 不支持，仅 img_url 单图 |
| 最长时长 | 15 秒 | 10-15 秒（因模型而异） |

---

## 其他更新

- **角色图支持上传替换**：角色卡片新增上传按钮，可以直接上传本地图片作为角色参考图，不再只依赖 AI 生成

---

## 项目地址 & 演示视频

- **GitHub**：https://github.com/twwch/AIComicBuilder
- **最新版本演示视频**：https://www.bilibili.com/video/BV1v4DZBmEiw/

---

> UCloud Seedance 文档：https://docs.ucloud.cn/modelverse/api_doc/video_api/doubao-seedance-1-5-pro-251215
>
> 通义万相 DashScope 文档：https://help.aliyun.com/zh/model-studio/video-generation
