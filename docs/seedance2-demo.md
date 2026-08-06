# 当 AIComicBuilder 接入 Seedance 2.0 的 API

GitHub：https://github.com/twwch/AIComicBuilder

## 项目简介

AIComicBuilder 是一个 AI 驱动的漫画/视频创作工具，通过 **剧本 → 角色 → 分镜 → 预览** 的工作流，将一段文字描述自动转化为连贯的视频内容。接入 Seedance 2.0 API 后，可以直接生成高质量的二次元动漫风格视频。

## 工作流程演示

### 1. 剧本生成

输入故事主题后，AI 自动生成完整剧本，包括场景描述、角色对白、镜头调度等。支持自定义视觉风格和色彩方案。

![剧本生成](https://cdn.jsdelivr.net/gh/twwch/images/AIComicBuilder/images/2026/04/剧本.png)

### 2. 角色提取

从剧本中自动提取角色信息，生成角色关系图和详细的角色描述。每个角色会生成多角度参考图，确保后续分镜中角色形象一致。

![角色提取](https://cdn.jsdelivr.net/gh/twwch/images/AIComicBuilder/images/2026/04/角色提取.png)

### 3. 分镜生成

基于剧本内容自动拆分分镜，支持「基于首尾帧」和「基于参考图」两种生成模式。可批量生成场景参考帧，并通过 Seedance 2.0 API 批量生成视频片段。

![分镜生成](https://cdn.jsdelivr.net/gh/twwch/images/AIComicBuilder/images/2026/04/分镜.png)

### 4. 预览与导出

所有分镜视频按顺序拼接，可在线预览完整影片。支持下载视频和合成最终作品。

![预览](https://cdn.jsdelivr.net/gh/twwch/images/AIComicBuilder/images/2026/04/预览.png)


### 5. 成本

10 个分镜视频生成任务，总消耗 ¥64.30。

![成本](https://cdn.jsdelivr.net/gh/twwch/images/AIComicBuilder/images/2026/04/成本.png)

完整视频：https://www.bilibili.com/video/BV1g5SDBSECs/