import os

_DASHSCOPE_KEY = ""
_DEEPSEEK_KEY = "sk-250f0db1077b4783b92d779ca9284f28"

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "") or _DASHSCOPE_KEY
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "") or _DEEPSEEK_KEY

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

WANX_MODEL = "wanx-v1"
WANX_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text2image/image-synthesis"
WANX_TASK_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"
