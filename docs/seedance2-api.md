使用说明
其他参数及使用方法和官方一样，只需要将域名从https://ark.cn-beijing.volces.com/api/v3改为http://123.57.80.82/seedance ，key换成我们的key即可。
注意如果需要生成类真人视频，一定要先提交自定义虚拟人像，获取资产id，然后用资产链接作为参考图链接生成，不要用网络链接。
模型ID：
Seedance2.0: doubao-seedance-2-0-260128
Seedance2.0-fast: doubao-seedance-2-0-fast-260128 
官方价格计费：
doubao-seedance-2-0-260128：
文/图生视频token价格：0.046 元/千tokens
视频生视频token价格：0.028 元/千 tokens
doubao-seedance-2-0-fast-260128:
文/图生视频token价格：0.037元/千tokens
视频生视频token价格：0.022元/千tokens
支持能力：
文生视频
图生视频-首帧
图生视频-首尾帧
多模态参考：图片参考、视频参考 、组合参考（图片+音频、图片+视频、视频+音频、图片+视频+音频）
编辑视频
延长视频
生成有声视频
联网搜索增强
返回视频尾帧
输出视频规格：输出分辨率（480p, 720p）、输出宽高比（21:9, 16:9, 4:3, 1:1, 3:4, 9:16）、输出时长（4~15 秒）、输出视频格式（mp4）
API格式：
字段：
content object[] 必选
输入给模型，生成视频的信息，支持文本、图片、音频、视频、样片任务 ID。支持以下几种组合：
• 文本
• 文本（可选）+ 图片
• 文本（可选）+ 视频
• 文本（可选）+ 图片 + 音频
• 文本（可选）+ 图片 + 视频
• 文本（可选）+ 视频 + 音频
• 文本（可选）+ 图片 + 视频 + 音频
信息类型：
• 文本信息object
输入给模型的提示词信息。
---
content.type string  必选
输入内容的类型，此处应为 text。
---
content.text string  必选
输入给模型的文本提示词，描述期望生成的视频。
支持中英文。建议中文不超过500字，英文不超过1000词。字数过多信息容易分散，模型可能因此忽略细节，只关注重点，造成视频缺失部分元素。提示词的更多使用技巧请参见 Seedance 提示词指南。
• 图片信息 object
输入给模型的图片信息。
---
content.type string 必选
输入内容的类型，此处应为 image_url。
---
content.image_url object  必选
输入给模型的图片对象。
---
content.image_url.url string  必选
图片 URL 、图片 Base64 编码、素材 ID。
- 图片 URL：填入图片的公网 URL。
- Base64 编码：将本地文件转换为 Base64 编码字符串，然后提交给大模型。遵循格式：data:image/<图片格式>;base64,<Base64编码>，注意 <图片格式> 需小写，如 data:image/png;base64,{base64_image}。
- 素材 ID：用于视频生成的预置素材及虚拟人像的 ID，遵循格式：asset://<ASSET_ID>，可从 素材&虚拟人像库 获取，详细使用请参见文档。
传入单张图片要求
• 格式：jpeg、png、webp、bmp、tiff、gif
• 宽高比（宽/高）： (0.4, 2.5)
• 宽高长度（px）：(300, 6000)
• 大小：单张图片小于 30 MB。请求体大小不超过 64 MB。大文件请勿使用Base64编码。
• 图片数量：
    ◦ 图生视频-首帧：1 张
    ◦ 图生视频-首尾帧：2 张
    ◦ Seedance 2.0 & 2.0 fast 多模态参考生视频：1~9 张
---
content.role string 条件必填
图片的位置或用途。
注意
• 图生视频-首帧、图生视频-首尾帧、多模态参考生视频（包括参考图、视频、音频）为 3 种互斥场景，不可混用。
• 多模态参考生视频可通过提示词指定参考图片作为首帧/尾帧，间接实现“首尾帧+多模态参考”效果。若需严格保障首尾帧和指定图片一致，优先使用图生视频-首尾帧（配置 role 为 first_frame / last_frame）。
---
图生视频-首帧
需要传入1个 image_url 对象
- 字段role取值：
- first_frame 或不填
---
图生视频-首尾帧
需要传入2个 image_url 对象
- 字段role取值：
- 首帧图片对应的字段 role 为：first_frame，必填
- 尾帧图片对应的字段 role 为：last_frame，必填
---
图生视频-参考图
可传入 1~9 个 image_url 对象
- 字段role取值：
- 每张参考图对应的字段 role 均为：reference_image，必填
• 视频信息 object
输入给模型的视频信息。仅 Seedance 2.0 & 2.0 fast 支持输入视频。
---
content.type string  必选
输入内容的类型，此处应为 video_url。
---
content.video_url object  必选
输入给模型的视频对象。
---
content.video_url.url string  必选
视频URL、素材 ID。
- 视频 URL：填入视频的公网 URL。
- 素材 ID：用于视频生成的预置素材及虚拟人像视频的 ID，遵循格式：asset://<ASSET_ID>。可从素材&虚拟人像库获取。
传入单个视频要求
• 视频格式：mp4、mov。
• 分辨率：480p、720p
• 时长：单个视频时长 [2, 15] s，最多传入 3 个参考视频，所有视频总时长不超过 15s。
• 尺寸：
    ◦ 宽高比（宽/高）：[0.4, 2.5]
    ◦ 宽高长度（px）：[300, 6000]
    ◦ 画面像素（宽 × 高）：[409600, 927408] ，示例：
        ▪ 画面尺寸 640×640=409600 满足最小值 ；
        ▪ 画面尺寸 834×1112=927408 满足最大值。
• 大小：单个视频不超过 50 MB。
• 帧率 (FPS)：[24, 60]
---
content.role string 条件必填
视频的位置或用途。当前仅支持 reference_video。
• 音频信息 object
输入给模型的音频信息。仅 Seedance 2.0 & 2.0 fast 支持输入音频。注意不可单独输入音频，应至少包含 1 个参考视频或图片。
---
content.type string  必选
输入内容的类型，此处应为 audio_url。
---
content.audio_url object  必选
输入给模型的音频对象。
---
content.audio_url.url string  必选
音频 URL 、音频 Base64 编码、素材 ID。
- 音频 URL：填入音频的公网 URL。
- Base64 编码：将本地文件转换为 Base64 编码字符串，然后提交给大模型。遵循格式：data:audio/<音频格式>;base64,<Base64编码>，注意 <音频格式> 需小写，如 data:audio/wav;base64,{base64_audio}。
- 素材 ID：用于视频生成的虚拟人的音频素材 ID，遵循格式：asset://<ASSET_ID>。可从素材&虚拟人像库获取。
传入单个音频要求
• 格式：wav、mp3
• 时长：单个音频时长 [2, 15] s，最多传入 3 段参考音频，所有音频总时长不超过 15 s。
• 大小：单个音频不超过 15 MB，请求体大小不超过 64 MB。大文件请勿使用Base64编码。
---
content.role string 条件必填
音频的位置或用途。当前仅支持 reference_audio 。
generate_audio boolean
Seedance 2.0 & 2.0 fast 默认值： true
控制生成的视频是否包含与画面同步的声音。
• true：模型输出的视频包含同步音频。模型会基于文本提示词与视觉内容，自动生成与之匹配的人声、音效及背景音乐。建议将对话部分置于双引号内，以优化音频生成效果。例如：男人叫住女人说：“你记住，以后不可以用手指指月亮。”
• false：模型输出的视频为无声视频。
说明
生成的有声视频均为单声道，和传入的音频声道数无关。
---
tools object[]
仅 Seedance 2.0 & 2.0 fast 支持
配置模型要调用的工具。
---
tools.type string
指定使用的工具类型。
• web_search：联网搜索工具。
说明
• 开启联网搜索后，模型会根据用户的提示词自主判断是否搜索互联网内容（如商品、天气等）。可提升生成视频的时效性，但也会增加一定的时延。
• 实际搜索次数可通过 查询视频生成任务 API 返回的 usage.tool_usage.web_search 字段获取，如果为 0 表示未搜索。
---
resolution  string
Seedance 2.0 & 2.0 fast  默认值：720p
视频分辨率，取值范围：
• 480p
• 720p
---
ratio string
Seedance 2.0 & 2.0 fast 默认值： adaptive
生成视频的宽高比例。不同宽高比对应的宽高像素值见下方表格。
• 16:9
• 4:3
• 1:1
• 3:4
• 9:16
• 21:9
• adaptive：根据输入自动选择最合适的宽高比
adaptive 适配规则
当配置 ratio 为 adaptive 时，模型会根据生成场景自动适配宽高比；实际生成的视频宽高比可通过 查询视频生成任务 API 返回的 ratio 字段获取。
• 文生视频：根据输入的提示词，智能选择最合适的宽高比。
• 首帧 / 首尾帧生视频：根据上传的首帧图片比例，自动选择最接近的宽高比。
• 多模态参考生视频：根据用户提示词意图判断，如果是首帧生视频/编辑视频/延长视频，以该图片/视频为准选择最接近的宽高比；否则，以传入的第一个媒体文件为准（优先级：视频＞图片）选择最接近的宽高比。
---

duration integer
Seedance 2.0 & 2.0 fast  默认值：5
生成视频时长，仅支持整数，单位：秒。
取值范围：
• [4,15] 或设置为-1
配置方法
• 指定具体时长：支持有效范围内的任一整数。
• 智能指定：设置为 -1，表示由模型在有效范围内自主选择合适的视频长度（整数秒）。实际生成视频的时长可通过 查询视频生成任务 API 返回的 duration 字段获取。注意视频时长与计费相关，请谨慎设置。
调用简介及示例
流程简介
任务接口是异步接口，视频生成任务流程
1. 创建视频生成任务接口创建视频生成任务
2. 定时使用查询接口查询视频生成任务状态
3. 任务 running，过段时间再查询任务状态
4. 任务完成，返回视频链接，在24小时内下载生成的视频文件
5. 创建视频生成任务
以下示例仅展示 Seedance 2.0 & 2.0 fast 新增能力，更多视频生成示例详见 创建视频生成任务 API。
多模态参考
curl http://123.57.80.82/seedance/contents/generations/tasks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{
    "model": "doubao-seedance-2-0-260128",
    "content": [
         {
            "type": "text",
            "text": "全程使用视频1的第一视角构图，全程使用音频1作为背景音乐。第一人称视角果茶宣传广告，seedance牌「苹苹安安」苹果果茶限定款；首帧为图片1，你的手摘下一颗带晨露的阿克苏红苹果，轻脆的苹果碰撞声；2-4 秒：快速切镜，你的手将苹果块投入雪克杯，加入冰块与茶底，用力摇晃，冰块碰撞声与摇晃声卡点轻快鼓点，背景音：「鲜切现摇」；4-6 秒：第一人称成品特写，分层果茶倒入透明杯，你的手轻挤奶盖在顶部铺展，在杯身贴上粉红包标，镜头拉近看奶盖与果茶的分层纹理；6-8 秒：第一人称手持举杯，你将图片2中的果茶举到镜头前（模拟递到观众面前的视角），杯身标签清晰可见，背景音「来一口鲜爽」，尾帧定格为图片2。背景声音统一为女生音色。"
        },
        {
            "type": "image_url",
            "image_url": {
                "url": "https://ark-project.tos-cn-beijing.volces.com/doc_image/r2v_tea_pic1.jpg"
            },
            "role": "reference_image"
        },
        {
            "type": "image_url",
            "image_url": {
                "url": "https://ark-project.tos-cn-beijing.volces.com/doc_image/r2v_tea_pic2.jpg"
            },
            "role": "reference_image"
        },
        {
          "type": "video_url",
          "video_url": {
              "url": "https://ark-project.tos-cn-beijing.volces.com/doc_video/r2v_tea_video1.mp4"
          },
          "role": "reference_video"
        },
        {
          "type": "audio_url",
          "audio_url": {
              "url": "https://ark-project.tos-cn-beijing.volces.com/doc_audio/r2v_tea_audio1.mp3"
          },
          "role": "reference_audio"
        }
    ],
    "generate_audio":true,
    "ratio": "16:9",
    "duration": 11,
    "watermark": false
}'
编辑视频
curl http://123.57.80.82/seedance/contents/generations/tasks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{
    "model": "doubao-seedance-2-0-260128",
    "content": [
        {
            "type": "text",
            "text": "将视频1礼盒中的香水替换成图片1中的面霜，运镜不变"
        },
        {
            "type": "image_url",
            "image_url": {
                "url": "https://ark-project.tos-cn-beijing.volces.com/doc_image/r2v_edit_pic1.jpg"
            },
            "role": "reference_image"
        },
        {
            "type": "video_url",
            "video_url": {
                "url": "https://ark-project.tos-cn-beijing.volces.com/doc_video/r2v_edit_video1.mp4"
            },
            "role": "reference_video"
        }
    ],
    "generate_audio": true,
    "ratio": "16:9",
    "duration": 5,
    "watermark": true
}'延长视频
curl http://123.57.80.82/seedance/contents/generations/tasks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{
    "model": "doubao-seedance-2-0-260128",
    "content": [
        {
            "type": "text",
            "text": "视频1中的拱形窗户打开，进入美术馆室内，接视频2，之后镜头进入画内，接视频3"
        },
        {
            "type": "video_url",
            "video_url": {
                "url": "https://ark-project.tos-cn-beijing.volces.com/doc_video/r2v_extend_video1.mp4"
            },
            "role": "reference_video"
        },
        {
            "type": "video_url",
            "video_url": {
                "url": "https://ark-project.tos-cn-beijing.volces.com/doc_video/r2v_extend_video2.mp4"
            },
            "role": "reference_video"
        },
        {
            "type": "video_url",
            "video_url": {
                "url": "https://ark-project.tos-cn-beijing.volces.com/doc_video/r2v_extend_video3.mp4"
            },
            "role": "reference_video"
        }
    ],
    "generate_audio": true,
    "ratio": "16:9",
    "duration": 8,
    "watermark": true
}'
使用联网搜索
仅支持文本生视频
curl http://123.57.80.82/seedance/contents/generations/tasks \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{
    "model": "doubao-seedance-2-0-260128",
    "content": [
         {
            "type": "text",
            "text": "微距镜头对准叶片上翠绿的玻璃蛙。焦点逐渐从它光滑的皮肤，转移到它完全透明的腹部，一颗鲜红的心脏正在有力地、规律地收缩扩张。"
        }
    ],
    "generate_audio":true,
    "ratio": "16:9",
    "duration": 11,
    "watermark": true,
    "tools": [
         {
             "type": "web_search"
         }
     ]
}'
查询视频生成任务
//请将 cgt-2026****hzc2z 替换为创建视频生成任务时获得的任务ID
curl -X GET http://123.57.80.82/seedance/contents/generations/tasks/cgt-2026****hzc2z \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY"   最佳实践-使用公共虚拟人像生成视频
公共虚拟人像库：
https://console.volcengine.com/ark/region:ark+cn-beijing/experience/vision?&modelId=doubao-seedance-2-0-260128&tab=GenVideo
平台提供公共虚拟人像素材库，目前您可以使用其中的图像素材来创建一个统一、完备的视频主角。帮助您更好地控制主角，并确保其形象在多段视频中保持一致，避免因为真人人脸限制导致角色无法统一的问题。
素材模态目前包含图片，并提供人物背景描述。每个素材对应一个独立素材 ID (asset ID)，指定角色人脸生成视频。
1. 检索需要使用的人像，支持使用自然语言检索及筛选框组合筛选。

@图片1 中美妆博主用中文进行介绍，妆容改为明艳大气，
去掉脸部反光，笑容甜美，近景镜头，
手持 @图片2 的面霜面向镜头展示，清新简约背景，
元气甜美风格。博主台词：挖到本命面霜了！
质地像云朵一样软糯，一抹就吸收，熬夜急救、补水保湿全搞定，素颜都自带柔光感。
在 Video Generation API 的 content.<模态>_url.url 字段中使用 素材 URI 生成视频。
输入的参考内容，包括人像素材，需符合视频生成限制，具体信息请查看使用限制。
示例代码：
import os
import time
# Install SDK:  pip install 'volcengine-python-sdk[ark]'
from volcenginesdkarkruntime import Ark 
client = Ark(
    base_url='http://123.57.80.82/seedance',
    api_key=os.environ.get("API_KEY"),
)
if __name__ == "__main__":
    print("----- create request -----")
    create_result = client.content_generation.tasks.create(
        model="doubao-seedance-2-0-260128", # Replace with Model ID 
        content=[
            {
                "type": "text",
                "text": "图片1中美妆博主用中文进行介绍，妆容改为明艳大气，去掉脸部反光，笑容甜美，近景镜头，手持图片2的面霜面向镜头展示，清新简约背景，元气甜美风格。博主台词：挖到本命面霜了！质地像云朵一样软糯，一抹就吸收，熬夜急救、补水保湿全搞定，素颜都自带柔光感。"
            },        
            {
                "type": "image_url",
                "image_url": {
                    "url": "asset://asset-20260224200602-qn7wr" # Asset ID
                },
                "role": "reference_image"
            },
            {
                "type": "image_url",
                "image_url": {
                    "url": "https://ark-project.tos-cn-beijing.volces.com/doc_image/r2v_edit_pic1.jpg"
                },
                "role": "reference_image"
            },
        ],
        generate_audio=True,
        ratio="16:9",
        duration=11,
        watermark=True,
    )
    print(create_result)
    print("----- polling task status -----")
    task_id = create_result.id
    while True:
        get_result = client.content_generation.tasks.get(task_id=task_id)
        status = get_result.status
        if status == "succeeded":
            print("----- task succeeded -----")
            print(get_result)
            break
        elif status == "failed":
            print("----- task failed -----")
            print(f"Error: {get_result.error}")
            break
        else:
            print(f"Current status: {status}, Retrying after 30 seconds...")
            time.sleep(30)入库流程

• 每个人物素材需至少提供一张正面图片文件。此外，您可按需提供该人物的其他图片、视频素材。
    ◦ 需确保每个人物组中的素材与该正面图片为同一人物。
• 您仅需上传视频生成任务中需要使用的素材。
    ◦ 素材文件需满足视频生成 API 对输入文件的要求：
传入单张图片要求
• 格式：jpeg、png、webp、bmp、tiff、gif
• 宽高比（宽/高）： (0.4, 2.5)
• 宽高长度（px）：(300, 6000)
• 大小：单张图片小于 30 MB。请求体大小不超过 64 MB。大文件请勿使用Base64编码。
传入单个视频要求
• 视频格式：mp4、mov。
• 分辨率：480p、720p
• 时长：单个视频时长 [2, 15] s，最多传入 3 个参考视频，所有视频总时长不超过 15s。
• 尺寸：
    ◦ 宽高比（宽/高）：[0.4, 2.5]
    ◦ 宽高长度（px）：[300, 6000]
    ◦ 画面像素（宽 × 高）：[409600, 927408] ，示例：
        ▪ 画面尺寸 640×640=409600 满足最小值 ；
        ▪ 画面尺寸 834×1112=927408 满足最大值。
• 大小：单个视频不超过 50 MB。
• 帧率 (FPS)：[24, 60]
1. 方舟将对您提供的素材进行审核，通过审核的素材将被上传至虚拟人像库。
2. 您可按 asset: //<asset_id> 规则拼接 URI，在 API 中使用对应素材生成视频：
{
    "type": "image_url",
    "image_url": {
        "url": "asset://asset-2026**********-*****"
    },
    "role": "reference_image"
},注意事项:仅支持使用已入库素材生成视频。
---
自定义虚拟人像素材接口
本文介绍素材资产（Assets）API 接口的参数。您可以使用以下 Assets API 接口创建、管理个人人像素材资产。
本文档仅限预览及邀测用户使用：
• 不承诺正式 API 上线100%一致。
• 仅限邀测用户阅读，请勿截图/分享给其他人员。
• 您需确保上传的虚拟人像符合以下条件：
    ◦ 您合法拥有该素材，并享有完整的使用及处分权限。素材不包含未获授权的第三方商标、标识类内容。
    ◦ 素材不得与任何自然人肖像或形象雷同，素材不存在抄袭、盗用情形，不会侵害任何第三方的人格权、知识产权等合法权益。
    ◦ 素材不包含违反法规、违背公序良俗、危害国家安全的内容。
素材资产（Assets）API 接口功能
素材资产的概念说明：
• Asset（素材资产）：一个素材文件（图片），是方舟 Seedance 2.0 系列模型可直接用于推理的可信资产。
    ◦ 仅需入库推理需使用的素材资产，不需使用的素材资产请勿入库。
    ◦ 仅可使用已入库素材资产的 Id (Asset ID) 进行视频生成，同一形象未入库素材无法使用。
CreateAsset
POST /open/CreateAsset
向指定的Asset Group（素材资产组合）内创建Asset（素材资产）。
curl -X POST "http://123.57.80.82/seedance/open/CreateAsset" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer API_KEY" \
  -d '{
    "AssetType": "Image",
    "URL": "https://img-blog.csdnimg.cn/img_convert/037d1406cd4b6b26b8108c3757b55650.png"
  }'请求参数
---
URL string 必填
传入的Asset（素材资产）的公共可访问地址。
---
Name string
Asset（素材资产）的名称，上限为64个字符。
---
AssetType string 必填
Asset（素材资产）的类型，当前仅支持传入图像。可选值：
• Image：Asset（素材资产）的类型为图像。
传入图像的要求说明
• 格式：jpeg、png、webp、bmp、tiff、gif、heic/heif
• 宽高比（宽/高）： (0.4, 2.5)
• 宽高长度（px）：(300, 6000)
• 大小：单张图片小于 30 MB。
---
返回参数
Id string
Asset（素材资产）的 Id。
---
返回示例：
{
"Id": "Asset-2026**********-*****"
}
ListAssets
POST /open/ListAssets
查询符合筛选条件的Assets（素材资产）列表。
curl -X POST "http://123.57.80.82/seedance/open/ListAssets" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-omei9f28eh4gbIUD928ehf2" \
  -d '{"PageNumber": 1, "PageSize": 10}'请求参数

Filter object 必填
搜索的过滤条件。
---
Filter.Statuses array
任务状态。
• Active：素材资产（Asset）已处理完毕，可以使用。
• Processing：素材资产（Asset）正在预处理，无法使用。
• Failed：素材资产（Asset）处理失败。
---
Filter.Name string
Asset（素材资产）的名称，上限为64个字符。
---
PageNumber int (i64) 必填
搜索页码，可用于列表分页功能，从 1 开始。例如："page_number": 1，即返回第一页的搜索结果。
---
PageSize int (i64) 必填
每页搜索结果的数量，上限为100。
---
SortBy string
用于排序的字段名称，默认值 createTime。支持以下类型：
• CreateTime：根据创建时间排序。
• UpdateTime：根据更新时间排序。
• GroupId：根据资产素材组的 Id 排序。
---
SortOrder string
排序顺序，默认值 Desc。可选值：
• Desc：降序
• Asc：升序
---
返回参数
Items array[]
符合筛选条件的Asset（素材资产）数组。
---
Items.Id string
Asset（素材资产）的 Id。
---
Items.name string
Asset（素材资产）的名称，上限为64个字符。
---
Items.URL string
Asset（素材资产）的公共可访问地址。
---
Items.GroupId string
Asset（素材资产）所属的 Asset Group（素材资产组合）的 Id。
---
Items.AssetType string
Asset（素材资产）的类型。
• Image：Asset（素材资产）的类型为图像。
---
Items.Status string
任务状态。
• Active：素材资产（Asset）已处理完毕，可以使用。
• Processing：素材资产（Asset）正在预处理，无法使用。
• Failed：素材资产（Asset）处理失败。
---
Items.Error object
错误信息。
---
Items.Error.Code string
错误码。
---
Items.Error.Message string
错误信息。
---
Items.ProjectName string
资源所属的项目名称。
---
Items.CreateTime string
创建时间。
---
Items.UpdateTime string
更新时间。
---
TotalCount int (i64)
返回总数。
---
PageNumber int (i64)
返回的页数。
---
PageSize int (i64)
每页搜索结果的数量，上限为100。
GetAsset
POST /open/GetAsset
获取单个Asset（素材资产）信息。
curl -X POST "http://123.57.80.82/seedance/open/GetAsset" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer API_KEY" \
  -d '{"Id": "asset-2026xxxxxxxxx"}'请求参数
Id string  必填
Asset（素材资产）的 Id。
---
返回参数
Id string
Asset（素材资产）的 Id。
---
Name string
Asset（素材资产）的名称，上限为64个字符。
---
URL  string
Asset（素材资产）的访问地址。
---
AssetType string
Asset（素材资产）的类型。
• Image：Asset（素材资产）的类型为图像。
---
Status string
任务状态。
• Active：素材资产（Asset）已处理完毕，可以使用。
• Processing：素材资产（Asset）正在预处理，无法使用。
• Failed：素材资产（Asset）处理失败。
---
Error object
错误信息。
---
Error.Code string
错误码。
---
Error.Message string
错误信息。
---
CreateTime string
创建时间。
---
UpdateTime  string
更新时间。
---
ProjectName string
资源所属的项目名称。
---
使用链路：
以下为使用 Asset API 创建素材资产并用于视频生成的使用链路：
1. 上传素材资产并等待预处理完成：调用 CreateAsset 接口上传图片素材，传入图片的公共访问URL，获得素材资产ID（Asset ID）。
由于上传的素材资产需经过预处理后才能使用，可轮询调用 GetAsset 接口查询素材状态，直至状态变为 Active。若状态为 Failed 则表示处理失败。
2. 在视频生成 API 中使用素材：当素材资产状态为 Active 后，将素材ID按 Asset://<Asset_Id> 的格式拼接成URL，在视频生成API（如Seedance 2.0系列模型）的请求中，将该URL作为参考图像的 image_url 传入，即可使用该素材资产生成视频。
3. 素材资产用于视频生成
当上传的素材资产状态为 Active 时，可将素材 Id 按 Asset: //<Asset_Id> 的规则拼接 URL，以在 视频生成 API 中使用对应的素材资产生成视频：
{
    "type": "image_url",
    "image_url": {
        "url": "asset://asset-2026**********-*****"
    },
    "role": "reference_image"
},