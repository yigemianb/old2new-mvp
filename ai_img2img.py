"""图生图（旧物改造）核心模块。

对接阿里云百炼「万相 · 通用图像编辑」wanx2.1-imageedit：
    1. 创建任务：POST /api/v1/services/aigc/image2image/image-synthesis
       （必须带 X-DashScope-Async: enable，input.function = description_edit）
    2. 轮询结果：GET  /api/v1/tasks/{task_id}
    3. 输入图片：base_image_url 支持公网 URL 或 `data:image/jpeg;base64,...`，
       因此本地照片无需先上传 OSS。

相比原先的纯占位实现，这里补齐了：
    * 真正把用户上传的旧物照片送进模型（原来完全没用到照片）；
    * 提示词工程：先锁定原物的轮廓 / 材质 / 主色，再描述改造目标与风格；
    * 图片预处理：EXIF 方向纠正、转 RGB、边长限制在接口要求的 512~2048；
    * 提交与轮询都带重试，错误码翻译成可执行的排查建议；
    * progress 回调，页面可显示真实进度；
    * 无 Key / 接口失败时降级为「基于原图的风格化预览」，页面不会空白；
    * 可配置改造强度 strength（越大越偏离原物）、数量、随机种子。

对外主要接口：
    generate_remake_images(...) -> RemakeResult
    build_edit_prompt(...)
    prepare_base_image(...)
    image_to_png_bytes / image_to_jpeg_bytes / images_to_zip
"""

from __future__ import annotations

import base64
import io
import random
import string
import time
import zipfile
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence
from uuid import uuid4

from PIL import (
    Image,
    ImageDraw,
    ImageEnhance,
    ImageFilter,
    ImageFont,
    ImageOps,
    ImageStat,
)

import config

ProgressFn = Callable[[float, str], None]

# Base64 编码后会膨胀约 1/3，接口要求图片 ≤ 10MB，这里给编码后的内容留足余量
_MAX_ENCODED_BYTES = 9 * 1024 * 1024
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_SUPPORTED_COUNT = (1, 4)

# 错误码 -> 可执行建议（前缀匹配，兼容 Throttling.RateQuota 这类子码）
_HINTS = {
    "InvalidApiKey": "检查 Key 是否粘贴完整、是否属于阿里云百炼（北京地域）",
    "Unauthorized": "检查 API Key 是否有效，或账号是否已开通百炼服务",
    "AccessDenied": "账号无该模型权限，请先在百炼控制台开通万相图像编辑",
    "Arrearage": "账户余额不足，请到百炼控制台充值后重试",
    "Throttling": "触发限流（并发任务上限 2），等几秒再试或减少生成数量",
    "DataInspectionFailed": "提示词或图片触发内容审核，请更换照片 / 换一种描述",
    "IPInfringementSuspect": "输入可能涉及侵权内容，请更换照片或描述",
    "InvalidParameter": "请检查图片：边长 512~4096 像素、大小不超过 10MB、格式为 JPG/PNG",
    "InternalError": "服务端临时异常，稍等片刻重试即可",
    "Timeout": "任务排队较久，可稍后重试，或把生成数量先调成 1",
    "NetworkError": "检查本机网络 / 代理设置后重试",
}


class ImageEditError(RuntimeError):
    """图生图接口调用失败，带错误码与排查建议。"""

    def __init__(self, message: str, code: str = "", hint: str = ""):
        super().__init__(message)
        self.code = code
        self.hint = hint

    def friendly(self) -> str:
        parts = [str(self)]
        if self.hint:
            parts.append(f"建议：{self.hint}")
        if self.code:
            parts.append(f"错误码：{self.code}")
        return "；".join(parts)


@dataclass
class RemakeResult:
    """一次图生图的结果，字段直接给 Streamlit 页面使用。"""

    images: list[Image.Image]
    status: str
    mode: str = "demo"  # api / demo
    prompt: str = ""
    task_id: str = ""
    error: str = ""
    warnings: list[str] = field(default_factory=list)
    elapsed: float = 0.0
    token: str = field(default_factory=lambda: uuid4().hex[:8])


# --------------------------------------------------------------------------- #
# 基础工具
# --------------------------------------------------------------------------- #
def _notify(progress: ProgressFn | None, ratio: float, text: str) -> None:
    """安全地回调进度，UI 出错不影响生成流程。"""
    if progress is None:
        return
    try:
        progress(max(0.0, min(1.0, float(ratio))), text)
    except TypeError:  # 兼容只接收比例的旧回调
        try:
            progress(max(0.0, min(1.0, float(ratio))))
        except Exception:
            pass
    except Exception:
        pass


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _sleep(seconds: float) -> None:
    """单独包一层，方便测试时替换，避免真的等待。"""
    time.sleep(seconds)


def _ensure_rgb(img: Image.Image) -> Image.Image:
    """统一转 RGB；透明背景（PNG 抠图）铺白底，避免变成黑底。"""
    if img.mode == "RGB":
        return img
    if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return img.convert("RGB")


def open_image(source: Any) -> Image.Image:
    """把 bytes / 路径 / PIL.Image 统一读成正常方向的 RGB 图。"""
    if isinstance(source, Image.Image):
        img = source.copy()
    elif isinstance(source, (bytes, bytearray)):
        img = Image.open(io.BytesIO(bytes(source)))
    else:
        img = Image.open(source)
    img.load()
    img = ImageOps.exif_transpose(img)
    return _ensure_rgb(img)


def prepare_base_image(source: Any, max_side: int | None = None, min_side: int | None = None) -> Image.Image:
    """预处理上传图：纠正方向、转 RGB、把边长收进接口允许的范围。

    接口要求宽高都在 512~4096 之间。超宽全景图先按 4:1 居中裁切，
    避免“压到 512 以下”或“放大后超过 4096”的两难。
    """
    max_side = int(max_side or config.IMG_MAX_SIDE)
    min_side = int(min_side or config.IMG_MIN_SIDE)
    img = open_image(source)

    width, height = img.size
    if min(width, height) > 0 and max(width, height) / min(width, height) > 4:
        if width >= height:
            new_width = max(1, height * 4)
            left = (width - new_width) // 2
            img = img.crop((left, 0, left + new_width, height))
        else:
            new_height = max(1, width * 4)
            top = (height - new_height) // 2
            img = img.crop((0, top, width, top + new_height))
        width, height = img.size

    scale = 1.0
    if max(width, height) > max_side:
        # 同时兼顾最长边与最短边，必要时允许最长边超过 max_side（仍在接口 4096 内）
        scale = max(max_side / float(max(width, height)), min_side / float(min(width, height)))
    elif min(width, height) < min_side:
        scale = min_side / float(min(width, height))

    if scale != 1.0:
        new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
        img = img.resize(new_size, Image.LANCZOS)
    return img


def encode_image_data_uri(img: Image.Image, quality: int = 92) -> str:
    """编码成 `data:image/jpeg;base64,...`，必要时降质 / 缩放以控制体积。"""
    if not isinstance(img, Image.Image):
        raise TypeError("encode_image_data_uri 需要 PIL.Image")
    working = _ensure_rgb(img)
    q = int(_clamp(quality, 60, 95))
    encoded = b""
    for _ in range(8):
        buffer = io.BytesIO()
        working.save(buffer, format="JPEG", quality=q, optimize=True, progressive=True)
        encoded = base64.b64encode(buffer.getvalue())
        if len(encoded) <= _MAX_ENCODED_BYTES:
            break
        if q > 70:
            q -= 8
        else:
            working = working.resize(
                (max(1, working.width * 3 // 4), max(1, working.height * 3 // 4)),
                Image.LANCZOS,
            )
            q = 85
    return "data:image/jpeg;base64," + encoded.decode("ascii")


def image_to_png_bytes(img: Image.Image) -> bytes:
    buffer = io.BytesIO()
    _ensure_rgb(img).save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def image_to_jpeg_bytes(img: Image.Image, max_side: int = 1200, quality: int = 85) -> bytes:
    """给社区数据库用的紧凑 JPEG，避免 BLOB 过大。"""
    working = _ensure_rgb(img)
    if max(working.size) > max_side:
        working.thumbnail((max_side, max_side), Image.LANCZOS)
    buffer = io.BytesIO()
    working.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
    return buffer.getvalue()


def images_to_zip(images: Sequence[Image.Image], prefix: str = "改造方案") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, image in enumerate(images):
            label = string.ascii_uppercase[index] if index < 26 else str(index + 1)
            archive.writestr(f"{prefix}_{label}.png", image_to_png_bytes(image))
    return buffer.getvalue()


def check_image_quality(img: Image.Image) -> list[str]:
    """给上传照片做几条轻量提示，减少“生成效果差”的困惑。"""
    warnings: list[str] = []
    width, height = img.size

    if min(width, height) < config.IMG_MIN_SIDE:
        warnings.append(
            f"原图分辨率偏低（{width}×{height}），建议上传更清晰的照片，改造细节会更准确"
        )

    thumb = img.copy()
    thumb.thumbnail((512, 512))
    edges = thumb.convert("L").filter(ImageFilter.FIND_EDGES)
    sharpness = ImageStat.Stat(edges).stddev[0]
    if sharpness < 8:
        warnings.append("照片可能偏模糊，建议对焦后重拍，AI 更容易识别旧物结构")

    brightness = ImageStat.Stat(thumb.convert("L")).mean[0]
    if brightness < 45:
        warnings.append("照片偏暗，建议在自然光下拍摄，避免模型误判材质")
    elif brightness > 212:
        warnings.append("照片可能过曝，建议避免强反光并减少背景杂物")

    return warnings


# --------------------------------------------------------------------------- #
# 提示词
# --------------------------------------------------------------------------- #
_CHANGE_PREFIXES = (
    "改造成一个",
    "改造成",
    "改造为一个",
    "改造为",
    "改成",
    "变为",
    "变成",
    "做成一个",
    "做成",
    "制作成",
)


def _strip_change_prefix(text: str) -> str:
    """用户常写“改成猫咪窝”，去掉动词避免出现“改造成改成…”的重复。"""
    cleaned = text.strip()
    for prefix in _CHANGE_PREFIXES:
        if cleaned.startswith(prefix):
            return cleaned[len(prefix):].strip() or cleaned
    return cleaned


def build_edit_prompt(
    old_item_desc: str,
    requirement: str,
    chosen_style: str = "",
    extra: str = "",
) -> str:
    """构造“指令编辑”提示词：先锁定原物特征，再要求改造成成品。"""
    old_item = (old_item_desc or "").strip() or "这件旧物"
    target = _strip_change_prefix(requirement) or "用到实处的新物品"
    style = (chosen_style or "").strip()

    parts = [
        f"保留原图中{old_item}的整体轮廓、材质纹理和主色调，把它改造成{target}。",
        "改造后的成品要结构完整、比例协调、接缝自然，看起来是真实手工完成的实物。",
    ]
    if style:
        parts.append(f"整体风格为{style}，配色、线条和装饰都要与风格统一。")
    if extra.strip():
        parts.append(extra.strip())
    parts.append("专业产品摄影，柔和自然光，干净简洁的背景，细节清晰，真实质感，高清。")

    # 接口限制：提示词最长 800 字符
    return "".join(parts)[:800]


# --------------------------------------------------------------------------- #
# 网络层
# --------------------------------------------------------------------------- #
def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {config.DASHSCOPE_API_KEY}",
        "Content-Type": "application/json",
        "X-DashScope-Async": "enable",
    }


def _post_json(url: str, headers: dict, payload: dict, timeout: int):
    import requests  # 延迟导入，方便离线跑单元测试

    return requests.post(url, headers=headers, json=payload, timeout=timeout)


def _get_json(url: str, headers: dict, timeout: int):
    import requests

    return requests.get(url, headers=headers, timeout=timeout)


def _download_bytes(url: str, timeout: int) -> bytes:
    import requests

    response = requests.get(url, timeout=timeout)
    if response.status_code != 200:
        raise ImageEditError(f"图片下载失败：HTTP {response.status_code}", code="DownloadError")
    return response.content


def _parse_json(response) -> dict:
    try:
        data = response.json()
    except Exception as exc:
        raise ImageEditError(
            "接口返回的内容不是合法 JSON",
            code=f"HTTP{getattr(response, 'status_code', '?')}",
            hint=str(getattr(response, "text", ""))[:200],
        ) from exc
    return data if isinstance(data, dict) else {}


def _hint_for(code: str) -> str:
    text = str(code or "")
    for prefix, hint in _HINTS.items():
        if text.startswith(prefix):
            return hint
    return ""


def _response_error(response, data: dict) -> ImageEditError:
    output = data.get("output") if isinstance(data.get("output"), dict) else {}
    code = str(data.get("code") or output.get("code") or f"HTTP{getattr(response, 'status_code', '?')}")
    message = str(
        data.get("message")
        or output.get("message")
        or str(getattr(response, "text", ""))[:300]
        or "未知错误"
    )
    return ImageEditError(f"图生图接口报错：{message}", code=code, hint=_hint_for(code))


def _request_with_retry(method: str, url: str, *, payload: dict | None = None, attempts: int | None = None):
    """提交 / 轮询统一入口：网络异常与 429、5xx 会重试，其余错误直接返回。"""
    attempts = int(attempts or config.IMG2IMG_RETRY)
    timeout = config.IMG2IMG_TIMEOUT
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            if method.upper() == "POST":
                response = _post_json(url, _headers(), payload or {}, timeout)
            else:
                response = _get_json(url, _headers(), timeout)
        except Exception as exc:  # 超时、连接失败等
            last_error = exc
            if attempt < attempts:
                _sleep(1.2 * attempt)
                continue
            raise ImageEditError(
                f"网络请求失败：{exc}", code="NetworkError", hint=_HINTS["NetworkError"]
            ) from exc

        status = int(getattr(response, "status_code", 0) or 0)
        if status in _RETRYABLE_STATUS and attempt < attempts:
            _sleep(1.5 * attempt)
            continue
        return response

    raise ImageEditError(
        f"网络请求失败：{last_error}", code="NetworkError", hint=_HINTS["NetworkError"]
    )


# --------------------------------------------------------------------------- #
# 图生图接口
# --------------------------------------------------------------------------- #
def submit_edit_task(
    base_image: Image.Image,
    prompt: str,
    *,
    strength: float | None = None,
    count: int = 3,
    seed: int | None = None,
    watermark: bool | None = None,
    model: str | None = None,
) -> str:
    """创建图像编辑任务，返回 task_id。"""
    if not config.DASHSCOPE_API_KEY:
        raise ImageEditError(
            "未配置 DashScope API Key",
            code="NoApiKey",
            hint="在侧边栏粘贴 Key，或设置环境变量 DASHSCOPE_API_KEY",
        )

    count = int(count)
    if not _SUPPORTED_COUNT[0] <= count <= _SUPPORTED_COUNT[1]:
        raise ImageEditError(
            f"生成数量必须为 1~4，当前是 {count}", code="InvalidParameter", hint="调整数量后重试"
        )

    if strength is None:
        strength = config.IMG_STRENGTH_DEFAULT
    parameters: dict[str, Any] = {
        "n": count,
        "strength": round(_clamp(float(strength), 0.0, 1.0), 3),
        "watermark": bool(config.IMG2IMG_WATERMARK if watermark is None else watermark),
    }
    if seed is not None:
        parameters["seed"] = int(seed) % 2147483648

    payload = {
        "model": model or config.WANX_EDIT_MODEL,
        "input": {
            "function": "description_edit",
            "prompt": prompt,
            "base_image_url": encode_image_data_uri(base_image),
        },
        "parameters": parameters,
    }

    response = _request_with_retry("POST", config.WANX_EDIT_ENDPOINT, payload=payload)
    data = _parse_json(response)
    if int(getattr(response, "status_code", 0) or 0) != 200:
        raise _response_error(response, data)

    task_id = (data.get("output") or {}).get("task_id")
    if not task_id:
        raise ImageEditError(
            "接口未返回 task_id", code="InvalidResponse", hint="稍后重试；若持续出现请检查模型名称"
        )
    return str(task_id)


def wait_for_task(
    task_id: str,
    progress: ProgressFn | None = None,
    timeout: float | None = None,
    interval: float | None = None,
) -> list[str]:
    """轮询任务直到成功，返回图片 URL 列表。"""
    timeout = float(timeout or config.IMG2IMG_MAX_WAIT)
    interval = float(interval or config.IMG2IMG_POLL_INTERVAL)
    started = time.time()
    ratio = 0.25

    while True:
        if time.time() - started > timeout:
            raise ImageEditError(
                f"等待生成超时（{timeout:.0f} 秒）",
                code="Timeout",
                hint="任务可能仍在排队，稍后重试或先把生成数量调成 1",
            )

        response = _request_with_retry(
            "GET", config.WANX_TASK_ENDPOINT.format(task_id=task_id)
        )
        data = _parse_json(response)
        if int(getattr(response, "status_code", 0) or 0) != 200:
            raise _response_error(response, data)

        output = data.get("output") or {}
        status = str(output.get("task_status") or "").upper()

        if status == "SUCCEEDED":
            results = output.get("results") or []
            urls = [
                item.get("url")
                for item in results
                if isinstance(item, dict) and item.get("url")
            ]
            if not urls:
                reasons = [
                    item.get("message")
                    for item in results
                    if isinstance(item, dict) and item.get("message")
                ]
                raise ImageEditError(
                    "任务成功但没有返回图片"
                    + (f"：{'；'.join(reasons)}" if reasons else ""),
                    code="EmptyResult",
                    hint="更换一张主体更清晰的照片，或简化改造描述后重试",
                )
            _notify(progress, 0.85, f"生成完成，正在下载 {len(urls)} 张方案…")
            return urls

        if status in {"FAILED", "CANCELED", "UNKNOWN"}:
            code = str(output.get("code") or status)
            message = str(output.get("message") or "任务执行失败")
            raise ImageEditError(f"图生图任务失败：{message}", code=code, hint=_hint_for(code))

        ratio = min(0.82, ratio + 0.035)
        label = {
            "PENDING": "任务排队中…",
            "RUNNING": "AI 正在改造原图…",
        }.get(status, f"任务状态：{status or '未知'}")
        _notify(progress, ratio, label)
        _sleep(interval)


def download_result_images(
    urls: Sequence[str], progress: ProgressFn | None = None, attempts: int | None = None
) -> list[Image.Image]:
    """下载生成结果；结果 URL 有效期 24 小时，所以下载后由页面保存 / 提供下载。"""
    attempts = int(attempts or config.IMG2IMG_RETRY)
    images: list[Image.Image] = []
    total = max(1, len(urls))

    for index, url in enumerate(urls):
        _notify(progress, 0.86 + 0.1 * (index / total), f"下载方案 {index + 1}/{total}…")
        last_error: Exception | None = None
        content: bytes | None = None
        for attempt in range(1, attempts + 1):
            try:
                content = _download_bytes(url, config.IMG2IMG_TIMEOUT)
                break
            except Exception as exc:
                last_error = exc
                if attempt < attempts:
                    _sleep(1.0 * attempt)
        if content is None:
            raise ImageEditError(
                f"生成结果下载失败：{last_error}",
                code="DownloadError",
                hint="重试一次通常可解决；结果链接仅 24 小时有效",
            )
        try:
            img = Image.open(io.BytesIO(content))
            img.load()
            images.append(img.convert("RGB"))
        except Exception as exc:
            raise ImageEditError(
                "下载到的生成结果不是有效图片", code="DownloadError"
            ) from exc

    return images


# --------------------------------------------------------------------------- #
# 演示模式（无 Key 或接口失败时的兜底）
# --------------------------------------------------------------------------- #
def _load_font(size: int):
    for path in (
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "DejaVuSans-Bold.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _add_badge(image: Image.Image, text: str) -> Image.Image:
    """在左下角加一个半透明角标，避免演示图被误认为真实 AI 结果。"""
    canvas = image.convert("RGBA")
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    size = max(14, min(canvas.size) // 26)
    font = _load_font(size)
    try:
        left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    except Exception:
        left, top, right, bottom = 0, 0, size * len(text) // 2, size
    text_w, text_h = right - left, bottom - top
    pad = max(6, size // 2)
    x0 = pad * 2
    y0 = canvas.height - text_h - pad * 4
    draw.rounded_rectangle(
        (x0, y0, x0 + text_w + pad * 2, y0 + text_h + pad * 2),
        radius=pad,
        fill=(15, 23, 42, 200),
    )
    draw.text((x0 + pad - left, y0 + pad - top), text, font=font, fill=(255, 255, 255, 235))
    return Image.alpha_composite(canvas, overlay).convert("RGB")


def _stylize_variant(base: Image.Image, index: int, strength: float, jitter: float) -> Image.Image:
    """用 Pillow 做三种“方案感”的调色，作为演示预览。"""
    img = base.copy()
    if max(img.size) > 1000:
        img.thumbnail((1000, 1000), Image.LANCZOS)

    amount = _clamp(0.2 + 0.55 * strength + jitter, 0.05, 0.95)
    variant = index % 4

    if variant == 0:  # 暖调
        warm = Image.new("RGB", img.size, (255, 197, 143))
        out = Image.blend(img, warm, 0.10 + 0.22 * amount)
        out = ImageEnhance.Color(out).enhance(1.10 + 0.35 * amount)
        out = ImageEnhance.Brightness(out).enhance(1.02)
        out = ImageEnhance.Contrast(out).enhance(1.03)
    elif variant == 1:  # 冷调双色
        gray = ImageOps.grayscale(img)
        duotone = ImageOps.colorize(gray, black="#14283A", white="#EAF2F4")
        out = Image.blend(img, duotone, 0.25 + 0.35 * amount)
        out = ImageEnhance.Contrast(out).enhance(1.08 + 0.1 * amount)
    elif variant == 2:  # 复古海报
        out = ImageOps.posterize(img, 6)
        out = ImageEnhance.Color(out).enhance(1.15 + 0.25 * amount)
        out = out.filter(ImageFilter.UnsharpMask(radius=2, percent=140, threshold=3))
    else:  # 明亮清新
        out = ImageEnhance.Brightness(img).enhance(1.06)
        out = ImageEnhance.Color(out).enhance(1.0 + 0.3 * amount)
        out = ImageEnhance.Contrast(out).enhance(1.05)
        out = out.filter(ImageFilter.SMOOTH_MORE)

    return out


def _demo_variants(
    base: Image.Image, count: int, strength: float, seed: int | None
) -> list[Image.Image]:
    rng = random.Random(int(seed) if seed is not None else 2024)
    jitter = rng.uniform(-0.04, 0.04)
    images: list[Image.Image] = []
    for index in range(max(1, count)):
        img = _stylize_variant(base, index, strength, jitter)
        images.append(_add_badge(img, f"DEMO {string.ascii_uppercase[index]}"))
    return images


# --------------------------------------------------------------------------- #
# 对外主函数
# --------------------------------------------------------------------------- #
def generate_remake_images(
    source: Any,
    old_item_desc: str,
    requirement: str = "",
    chosen_style: str = "",
    count: int = 3,
    strength: float | None = None,
    seed: int | None = None,
    progress: ProgressFn | None = None,
) -> RemakeResult:
    """旧物照片 -> 改造效果图。

    Args:
        source: 上传的图片（bytes / 路径 / PIL.Image）。
        old_item_desc: 旧物描述，例如“旧牛仔外套”。
        requirement: 改造目标，例如“改成猫咪窝，带软垫”。
        chosen_style: 风格偏好，可空。
        count: 方案数量，1~4。
        strength: 改造强度 0~1，越大越偏离原图；默认取配置值。
        seed: 随机种子，传相同值可复现；None 表示每次随机。
        progress: 进度回调 ``progress(ratio, text)``。

    Returns:
        RemakeResult：图片列表、状态文案、提示词、错误信息等。
    """
    started = time.time()
    count = int(count)
    if not _SUPPORTED_COUNT[0] <= count <= _SUPPORTED_COUNT[1]:
        raise ValueError(f"生成数量必须为 1~4，当前是 {count}")

    if strength is None:
        strength = config.IMG_STRENGTH_DEFAULT
    strength = _clamp(float(strength), config.IMG_STRENGTH_MIN, config.IMG_STRENGTH_MAX)

    _notify(progress, 0.05, "正在检查并预处理原图…")
    raw = open_image(source)
    warnings = check_image_quality(raw)
    base = prepare_base_image(raw)
    prompt = build_edit_prompt(old_item_desc, requirement, chosen_style)

    def elapsed() -> float:
        return round(time.time() - started, 1)

    if not config.DASHSCOPE_API_KEY:
        _notify(progress, 0.45, "未配置 Key，生成本地演示预览…")
        images = _demo_variants(base, count, strength, seed)
        _notify(progress, 1.0, "演示预览已生成")
        return RemakeResult(
            images=images,
            status=(
                "当前为演示模式：未调用图生图 API，下面只是基于原图的调色预览。"
                "在侧边栏填入 DashScope Key 后，会真实调用 wanx2.1-imageedit 生成改造效果图。"
            ),
            mode="demo",
            prompt=prompt,
            warnings=warnings,
            elapsed=elapsed(),
        )

    try:
        _notify(progress, 0.12, "正在提交改造任务…")
        task_id = submit_edit_task(
            base, prompt, strength=strength, count=count, seed=seed
        )
        _notify(progress, 0.22, f"任务已提交（{task_id[:8]}），等待 AI 处理…")
        urls = wait_for_task(task_id, progress=progress)
        images = download_result_images(urls, progress=progress)
        _notify(progress, 1.0, "全部完成")
        return RemakeResult(
            images=images,
            status=(
                f"图生图完成：{len(images)} 个方案 · 改造强度 {strength:.0%} · "
                f"耗时 {elapsed():.1f}s"
            ),
            mode="api",
            prompt=prompt,
            task_id=task_id,
            warnings=warnings,
            elapsed=elapsed(),
        )
    except ImageEditError as exc:
        # 保留错误信息，同时给出可看的预览，避免页面空白
        _notify(progress, 0.6, "接口调用失败，切换到本地演示预览…")
        images = _demo_variants(base, count, strength, seed)
        _notify(progress, 1.0, "已用演示预览代替")
        return RemakeResult(
            images=images,
            status="⚠️ 图生图接口调用失败，以下为本地演示预览。",
            mode="demo",
            prompt=prompt,
            error=exc.friendly(),
            warnings=warnings,
            elapsed=elapsed(),
        )
