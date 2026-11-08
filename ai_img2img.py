import time
import requests
from io import BytesIO
from PIL import Image, ImageDraw
import config


def generate_remake_images(old_item_desc: str, requirement: str, count: int = 3):
    prompt = (
        f"将{old_item_desc}改造成{requirement}，"
        f"改造后的成品效果图，高质量，细节清晰，实拍风格，光线自然"
    )
    if not config.DASHSCOPE_API_KEY:
        return _mock_images(prompt, count), "演示模式（未配置图生图API）"
    try:
        return _call_wanx(prompt, count), "✅ 真实AI生成"
    except Exception as e:
        return _mock_images(prompt, count), f"⚠️ 图生图失败({e})，已回退演示模式"


def _call_wanx(prompt: str, count: int):
    headers = {
        "Authorization": f"Bearer {config.DASHSCOPE_API_KEY}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }
    payload = {
        "model": config.WANX_MODEL,
        "input": {"prompt": prompt},
        "parameters": {"size": "1024*1024", "n": count},
    }
    resp = requests.post(config.WANX_ENDPOINT, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    task_id = resp.json()["output"]["task_id"]

    for _ in range(60):
        time.sleep(2)
        r = requests.get(
            config.WANX_TASK_ENDPOINT.format(task_id=task_id),
            headers={"Authorization": f"Bearer {config.DASHSCOPE_API_KEY}"},
            timeout=30,
        )
        data = r.json()["output"]
        if data["task_status"] == "SUCCEEDED":
            images = []
            for res in data["results"]:
                img_resp = requests.get(res["url"], timeout=30)
                images.append(Image.open(BytesIO(img_resp.content)))
            return images
        if data["task_status"] == "FAILED":
            raise RuntimeError("图生图任务失败")
    raise TimeoutError("图生图超时，请重试")


def _mock_images(prompt: str, count: int):
    images = []
    palettes = [(180, 200, 220), (200, 180, 210), (170, 210, 190)]
    for i in range(count):
        img = Image.new("RGB", (512, 512), color=palettes[i % len(palettes)])
        draw = ImageDraw.Draw(img)
        draw.text((20, 230), f"[演示占位] 效果图 #{i + 1}", fill=(50, 50, 50))
        draw.text((20, 260), prompt[:40], fill=(80, 80, 80))
        images.append(img)
    return images
