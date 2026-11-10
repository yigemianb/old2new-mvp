"""全局配置。

安全提示：API Key 只从环境变量读取，或在页面侧边栏临时粘贴，
不要把真实 Key 写进源码 / 提交到公开仓库。
"""

import os

# ============ API Key ============
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "").strip()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()

# ============ 文案生成（DeepSeek） ============
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# ============ 图生图（阿里云百炼 · 万相通用图像编辑） ============
# 文档：https://help.aliyun.com/zh/model-studio/wanx-image-edit
# 该接口只支持异步：先创建任务，再轮询 /api/v1/tasks/{task_id}
WANX_EDIT_MODEL = "wanx2.1-imageedit"
WANX_EDIT_ENDPOINT = (
    "https://dashscope.aliyuncs.com/api/v1/services/aigc/image2image/image-synthesis"
)
WANX_TASK_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"

# 接口对输入图片的要求：宽高 512~4096 像素、文件 ≤ 10MB。
# 这里留一点余量：最长边限制 2048，Base64 后控制在 9MB 内。
IMG_MAX_SIDE = 2048
IMG_MIN_SIDE = 512
IMG_MAX_UPLOAD_MB = 20

# 改造强度：0 最接近原图，1 改动最大（接口默认 0.5）
IMG_STRENGTH_DEFAULT = 0.65
IMG_STRENGTH_MIN = 0.1
IMG_STRENGTH_MAX = 0.95

IMG2IMG_TIMEOUT = 30          # 单次 HTTP 请求超时（秒）
IMG2IMG_POLL_INTERVAL = 1.5   # 轮询任务状态的间隔（秒）
IMG2IMG_MAX_WAIT = 180        # 等待任务完成的最长时间（秒）
IMG2IMG_RETRY = 3             # 网络类错误的尝试次数
IMG2IMG_WATERMARK = False     # 生成图右下角是否加“AI生成”水印
