# 旧物创意改造平台 · 图生图完善版

Streamlit MVP：上传旧物照片 → AI 生成改造效果图 → 输出实操教程 → 发布到社区。

本版重点补完 **图生图**：原实现的 `generate_remake_images()` 完全没用到用户上传的照片，
永远返回三张纯色占位图，`_call_wanx()` 也从未被调用。现在改为真实调用
[万相通用图像编辑](https://help.aliyun.com/zh/model-studio/wanx-image-edit)（`wanx2.1-imageedit`），
以原图为底图做“指令编辑”，保留旧物的轮廓、材质和主色。

## 快速开始

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

打开页面后：

1. 在左侧「图生图 Key（DashScope）」粘贴阿里云百炼 API Key；
2. 上传旧物照片，填写旧物描述与改造需求；
3. 可选择生成数量（1~4）与改造强度（0.3~0.9）；
4. 点「🚀 生成改造方案」，等待 5~30 秒。

也可以用环境变量（推荐，避免 Key 写进代码）：

```bash
set DASHSCOPE_API_KEY=sk-xxxx
set DEEPSEEK_API_KEY=sk-xxxx
```

> 图生图需要**华北2（北京）地域**的百炼 API Key。

## 图生图链路

```
上传图片 bytes
   │  prepare_base_image：EXIF 方向纠正 / RGB / 边长限制 512~2048
   ▼
data:image/jpeg;base64,...（不依赖 OSS，本地图可直接送）
   │  POST /api/v1/services/aigc/image2image/image-synthesis
   │  X-DashScope-Async: enable
   │  input.function = description_edit
   │  parameters = { n, strength, seed?, watermark }
   ▼
task_id → 每 1.5s GET /api/v1/tasks/{task_id}
   │  PENDING / RUNNING / SUCCEEDED / FAILED
   ▼
下载结果图（URL 24 小时有效）→ 页面展示 / PNG 下载 / 打包 ZIP / 发布社区
```

关键参数：

| 参数 | 作用 | 本项目取值 |
| --- | --- | --- |
| `function` | 编辑方式 | `description_edit`（按指令改内容） |
| `strength` | 改造幅度，0 接近原图，1 改动最大 | 页面滑块，默认 0.65 |
| `n` | 一次生成几张 | 页面滑块 1~4 |
| `seed` | 复现同一结果 | 「换一批方案」时随机 |
| `base_image_url` | 底图 | 本地图转 Base64 data URI |

按生成张数计费（官方约 $0.02/张）；无 Key 的演示模式不消耗额度，
接口失败后的降级预览只是兜底，不代表没有产生费用。

## 无 Key / 调用失败时会怎样

- **无 Key**：进入演示模式，用 Pillow 对原图做暖调 / 冷调双色 / 复古海报三种调色，
  左下角标注 `DEMO A/B/C`，页面明确提示“未调用 API”。
- **有 Key 但接口报错**：页面顶部显示可读的错误原因与排查建议（见下表），
  同时给出本地预览，不会白屏、也不会静默失败。

| 错误码 | 含义 | 处理建议 |
| --- | --- | --- |
| `InvalidApiKey` | Key 无效 | 检查是否完整、是否北京地域百炼 Key |
| `Arrearage` | 欠费 | 百炼控制台充值 |
| `Throttling` | 限流（并发 2） | 等几秒重试，或减少数量 |
| `DataInspectionFailed` | 内容审核 | 换照片 / 换描述 |
| `InvalidParameter` | 参数不合法 | 边长 512~4096、≤10MB、JPG/PNG |
| `InternalError` | 服务异常 | 稍后重试 |

## 本次修改清单

`ai_img2img.py`（重写）

- 上传图真正参与生成：预处理后以 Base64 传给 `wanx2.1-imageedit`；
- 提示词工程：锁定原物“轮廓 + 材质纹理 + 主色调”，再描述改造目标与风格，
  并去掉“改成/改造成”这类前缀，避免“改造成改成……”的病句；
- 提交与轮询都带重试（网络异常、429、5xx），错误码翻译成可执行建议；
- `progress(ratio, text)` 回调：页面显示真实进度，而不是干等；
- 无 Key / 失败时降级为“基于原图的风格化预览”，并在结果里带回错误原因；
- 新增图片质量提示：分辨率过低、偏模糊、偏暗/过曝；
- 新增导出：单图 PNG、全部方案 ZIP、社区用压缩 JPEG；
- 删除从未被调用的旧 `_call_wanx()`（走的是文生图端点，参数也不对）。

`app.py`

- 把 `uploaded.getvalue()` 传进图生图（原来照片根本没往下传）；
- 生成结果、教程存进 `session_state`：点下载/发布不会再让结果消失；
- 三个方案支持逐个下载、打包下载、「换一批方案」；
- 社区发布改为发布 AI 效果图（可选原图），并使用压缩后的 JPEG，避免 BLOB 过大；
- 修复 `st.switch_page("app.py")` 误用：案例页改为跳转 + 预填旧物/需求；
- 增加生成数量、改造强度滑块，风格与数量在提交时一起生效。

`config.py`

- 增加图生图模型、端点、图片尺寸/体积、轮询与重试等配置；
- **移除源码里硬编码的 DeepSeek Key**（该 Key 已随压缩包外泄，请到
  <https://platform.deepseek.com> 删除并重新生成，再通过环境变量或侧边栏填入）。

## 测试

```bash
python -m unittest discover -s tests -v
```

13 个用例全部离线运行（不联网、不消耗额度）：提示词、图片预处理、Base64 编码、
演示模式、接口成功/失败/超时/任务失败、ZIP 与 JPEG 导出。

## 已知限制

- 图生图是“指令编辑”，不是“结构重绘”：极端改造（如把外套改成猫窝）仍可能保留
  较多原物形状，可把强度调到 0.8+ 并写清结构要求；
- 单次最多 4 张、并发任务上限 2，批量生成会串行排队；
- 生成结果 URL 仅 24 小时有效，需要留存请及时下载（页面已提供）。
