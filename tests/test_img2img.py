"""图生图模块单元测试（不联网、不消耗 API 额度）。

运行：
    python -m unittest discover -s tests -v
"""

import io
import json
import sys
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ai_img2img as m  # noqa: E402
import config  # noqa: E402


def _png_bytes(size=(640, 480), color=(120, 160, 200)) -> bytes:
    image = Image.new("RGB", size, color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class FakeResponse:
    def __init__(self, status_code=200, data=None, text=""):
        self.status_code = status_code
        self._data = {} if data is None else data
        self.text = text or json.dumps(self._data, ensure_ascii=False)

    def json(self):
        if isinstance(self._data, Exception):
            raise self._data
        return self._data


class Img2ImgTestCase(unittest.TestCase):
    def setUp(self):
        self._key = config.DASHSCOPE_API_KEY
        self._post = m._post_json
        self._get = m._get_json
        self._sleep = m._sleep
        self._download = m._download_bytes
        m._sleep = lambda seconds: None
        config.DASHSCOPE_API_KEY = ""

    def tearDown(self):
        config.DASHSCOPE_API_KEY = self._key
        m._post_json = self._post
        m._get_json = self._get
        m._sleep = self._sleep
        m._download_bytes = self._download

    # ---------------- 提示词 ----------------
    def test_prompt_keeps_original_features_and_removes_duplicate_verb(self):
        prompt = m.build_edit_prompt("旧牛仔外套", "改成猫咪窝，带软垫", "简约北欧风")
        self.assertIn("旧牛仔外套", prompt)
        self.assertIn("猫咪窝", prompt)
        self.assertNotIn("改造成改成", prompt)
        self.assertIn("简约北欧风", prompt)
        self.assertIn("材质纹理", prompt)
        self.assertLessEqual(len(prompt), 800)

    def test_prompt_without_optional_fields(self):
        prompt = m.build_edit_prompt("玻璃瓶", "")
        self.assertIn("玻璃瓶", prompt)
        self.assertIn("产品摄影", prompt)

    # ---------------- 图片预处理 ----------------
    def test_prepare_downscales_large_and_upscales_small(self):
        large = m.prepare_base_image(Image.new("RGB", (5000, 3000)))
        self.assertEqual(max(large.size), config.IMG_MAX_SIDE)
        self.assertAlmostEqual(large.size[0] / large.size[1], 5 / 3, places=2)

        small = m.prepare_base_image(Image.new("RGB", (300, 200)))
        self.assertEqual(min(small.size), config.IMG_MIN_SIDE)

    def test_prepare_handles_extreme_aspect(self):
        wide = m.prepare_base_image(Image.new("RGB", (3000, 600)))
        self.assertGreaterEqual(min(wide.size), config.IMG_MIN_SIDE)
        self.assertLessEqual(max(wide.size), 4096)

    def test_data_uri_is_valid_and_compact(self):
        uri = m.encode_image_data_uri(Image.new("RGB", (1024, 1024), (90, 120, 150)))
        self.assertTrue(uri.startswith("data:image/jpeg;base64,"))
        self.assertLess(len(uri), 9 * 1024 * 1024)

    def test_transparent_png_gets_white_background(self):
        rgba = Image.new("RGBA", (600, 600), (0, 0, 0, 0))
        rgba.paste((200, 50, 50, 255), (150, 150, 450, 450))
        rgb = m.open_image(rgba)
        self.assertEqual(rgb.mode, "RGB")
        self.assertGreater(min(rgb.getpixel((5, 5))), 240)

    # ---------------- 演示模式 ----------------
    def test_demo_mode_returns_stylized_variants(self):
        events = []
        result = m.generate_remake_images(
            _png_bytes(),
            "旧牛仔外套",
            "改成猫咪窝",
            count=3,
            progress=lambda ratio, text: events.append((ratio, text)),
        )
        self.assertEqual(result.mode, "demo")
        self.assertEqual(len(result.images), 3)
        self.assertTrue(result.status)
        self.assertTrue(result.prompt)
        self.assertEqual(events[0][0], 0.05)
        self.assertEqual(events[-1][0], 1.0)
        self.assertNotEqual(result.images[0].tobytes(), m.open_image(_png_bytes()).tobytes())

    def test_demo_mode_rejects_invalid_count(self):
        with self.assertRaises(ValueError):
            m.generate_remake_images(_png_bytes(), "旧物", "改造", count=5)

    def test_quality_warnings_for_low_res_dark_photo(self):
        warnings = m.check_image_quality(Image.new("RGB", (240, 180), (10, 10, 10)))
        self.assertTrue(any("分辨率" in item for item in warnings))
        self.assertTrue(any("偏暗" in item for item in warnings))

    # ---------------- 真实接口（用假响应） ----------------
    def test_api_success_flow(self):
        config.DASHSCOPE_API_KEY = "sk-test"
        captured = {}

        def fake_post(url, headers, payload, timeout):
            captured["url"] = url
            captured["payload"] = payload
            captured["headers"] = headers
            return FakeResponse(200, {"output": {"task_id": "task-1", "task_status": "PENDING"}})

        statuses = iter(
            [
                FakeResponse(200, {"output": {"task_status": "PENDING"}}),
                FakeResponse(
                    200,
                    {
                        "output": {
                            "task_status": "SUCCEEDED",
                            "results": [{"url": "https://example.com/a.png"}, {"url": "https://example.com/b.png"}],
                        }
                    },
                ),
            ]
        )

        m._post_json = fake_post
        m._get_json = lambda url, headers, timeout: next(statuses)
        m._download_bytes = lambda url, timeout: _png_bytes((512, 512), (30, 60, 90))

        result = m.generate_remake_images(
            _png_bytes(), "旧键盘", "做成墙面装饰", "工业风", count=2, strength=0.7
        )

        self.assertEqual(result.mode, "api")
        self.assertEqual(len(result.images), 2)
        self.assertEqual(result.task_id, "task-1")
        self.assertEqual(captured["headers"]["X-DashScope-Async"], "enable")
        self.assertEqual(captured["payload"]["model"], config.WANX_EDIT_MODEL)
        self.assertEqual(captured["payload"]["input"]["function"], "description_edit")
        self.assertTrue(captured["payload"]["input"]["base_image_url"].startswith("data:image/jpeg;base64,"))
        self.assertEqual(captured["payload"]["parameters"]["n"], 2)
        self.assertAlmostEqual(captured["payload"]["parameters"]["strength"], 0.7)

    def test_api_error_falls_back_to_demo_with_reason(self):
        config.DASHSCOPE_API_KEY = "sk-bad"
        m._post_json = lambda url, headers, payload, timeout: FakeResponse(
            401, {"code": "InvalidApiKey", "message": "Invalid API-key provided."}
        )

        result = m.generate_remake_images(_png_bytes(), "旧物", "改造成收纳盒", count=1)
        self.assertEqual(result.mode, "demo")
        self.assertIn("InvalidApiKey", result.error)
        self.assertIn("Key", result.error)
        self.assertEqual(len(result.images), 1)

    def test_task_failed_raises_image_edit_error(self):
        config.DASHSCOPE_API_KEY = "sk-test"
        m._post_json = lambda url, headers, payload, timeout: FakeResponse(
            200, {"output": {"task_id": "task-2", "task_status": "PENDING"}}
        )
        m._get_json = lambda url, headers, timeout: FakeResponse(
            200, {"output": {"task_status": "FAILED", "code": "DataInspectionFailed", "message": "审核未通过"}}
        )

        result = m.generate_remake_images(_png_bytes(), "旧物", "改造成摆件", count=1)
        self.assertEqual(result.mode, "demo")
        self.assertIn("DataInspectionFailed", result.error)
        self.assertIn("审核", result.error)

    def test_wait_for_task_timeout(self):
        m._get_json = lambda url, headers, timeout: FakeResponse(
            200, {"output": {"task_status": "RUNNING"}}
        )
        with self.assertRaises(m.ImageEditError) as ctx:
            m.wait_for_task("task-3", timeout=0.01, interval=0)
        self.assertEqual(ctx.exception.code, "Timeout")

    def test_network_error_is_wrapped(self):
        config.DASHSCOPE_API_KEY = "sk-test"

        def boom(*args, **kwargs):
            raise ConnectionError("connection reset")

        m._post_json = boom
        with self.assertRaises(m.ImageEditError) as ctx:
            m.submit_edit_task(Image.new("RGB", (640, 480)), "测试提示词")
        self.assertEqual(ctx.exception.code, "NetworkError")

    # ---------------- 导出 ----------------
    def test_zip_and_jpeg_exports(self):
        images = [Image.new("RGB", (800, 600), (i * 40, 100, 150)) for i in range(2)]
        archive = m.images_to_zip(images)
        self.assertTrue(archive.startswith(b"PK"))
        jpeg = m.image_to_jpeg_bytes(images[0], max_side=400)
        self.assertTrue(jpeg.startswith(b"\xff\xd8"))
        self.assertLessEqual(max(m.open_image(jpeg).size), 400)


if __name__ == "__main__":
    unittest.main()
