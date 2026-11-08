from openai import OpenAI
import config


def generate_tutorial(old_item_desc: str, requirement: str, chosen_style: str = ""):
    prompt = _build_prompt(old_item_desc, requirement, chosen_style)
    if not config.DEEPSEEK_API_KEY:
        return _mock_tutorial(old_item_desc, requirement) + "\n\n---\n[演示模式：未配置LLM API]"
    try:
        client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)
        resp = client.chat.completions.create(
            model=config.DEEPSEEK_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "你是一位手工改造达人，擅长把旧物改造成实用美观的新物品。请输出结构化、可操作的改造教程。",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
            max_tokens=1500,
        )
        return resp.choices[0].message.content
    except Exception as e:
        return _mock_tutorial(old_item_desc, requirement) + f"\n\n---\n[⚠️ LLM调用失败({e})。如提示余额不足请登录 platform.deepseek.com 充值1元]"


def _build_prompt(old_item_desc: str, requirement: str, chosen_style: str):
    style_hint = f"，风格偏好：{chosen_style}" if chosen_style else ""
    return f"""请为以下旧物改造生成一份详细的实操教程：

【旧物】{old_item_desc}
【改造目标】{requirement}{style_hint}

请严格按以下格式输出：

## 材料清单
- 列出所需全部材料与工具

## 改造步骤
1. 第一步：详细操作说明
2. 第二步：...
（共6-8步，每步含具体操作）

## 避坑指南
- 列出3-5条注意事项

## 难度评级
简单/中等/困难 + 理由 + 预计耗时
"""


def _mock_tutorial(old_item_desc: str, requirement: str):
    return f"""## 材料清单
- {old_item_desc} ×1
- 剪刀、针线、软垫填充棉
- 装饰配件（按需）

## 改造步骤
1. 清洗并晾干旧物，检查破损部位
2. 按改造目标裁剪出基础形状
3. 缝合主体结构，预留填充口
4. 填入软垫材料，调整饱满度
5. 封口缝合，整理外观
6. 添加装饰细节，完成成品

## 避坑指南
- 裁剪前先用纸样比对，避免一次裁剪失误
- 缝合时注意走线均匀，防止填充物外漏
- 填充量适中，过多影响手感过少影响定型

## 难度评级
简单 - 适合手工零基础新手，约1小时可完成

---
[注：当前为演示模板，配置 DEEPSEEK_API_KEY 后将生成针对「{old_item_desc}→{requirement}」的个性化教程]
"""
