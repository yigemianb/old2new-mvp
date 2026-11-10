import io
import random

import streamlit as st

import config
from ai_img2img import (
    generate_remake_images,
    image_to_jpeg_bytes,
    image_to_png_bytes,
    images_to_zip,
    prepare_base_image,
)
from ai_tutorial import generate_tutorial
from cases import CASES, recommend_cases
from community import init_db, like_work, list_exchanges, list_works, publish_exchange, publish_work

st.set_page_config(page_title="旧物创意改造平台", page_icon="♻️", layout="wide")
init_db()

NAV_OPTIONS = ["🛠️ 改造工具", "📚 案例灵感", "🌐 社区广场"]
STYLE_OPTIONS = ["", "简约北欧风", "日式原木风", "工业风", "复古风", "可爱卡通风"]

# 从「案例灵感」跳转过来时，先把目标页写进 session_state，再渲染导航
_nav_to = st.session_state.pop("nav_to", None)
if _nav_to in NAV_OPTIONS:
    st.session_state["nav"] = _nav_to
st.session_state.setdefault("nav", NAV_OPTIONS[0])

page = st.sidebar.selectbox("📍 功能导航", NAV_OPTIONS, key="nav")

with st.sidebar:
    st.divider()
    st.header("⚙️ API 配置")
    st.caption("直接粘贴 key 即可，无需设环境变量；也可用环境变量 DASHSCOPE_API_KEY / DEEPSEEK_API_KEY")
    img_key = st.text_input(
        "图生图 Key（DashScope）", type="password", placeholder="粘贴阿里云百炼 DashScope key"
    )
    llm_key = st.text_input(
        "LLM Key（DeepSeek）", type="password", placeholder="粘贴 DeepSeek key"
    )
    if img_key:
        config.DASHSCOPE_API_KEY = img_key.strip()
    if llm_key:
        config.DEEPSEEK_API_KEY = llm_key.strip()
    st.write(f"图生图 API: {'✅ 已配置' if config.DASHSCOPE_API_KEY else '❌ 演示模式'}")
    st.write(f"LLM API: {'✅ 已配置' if config.DEEPSEEK_API_KEY else '❌ 演示模式'}")
    with st.expander("💡 图生图说明"):
        st.caption(
            "图生图使用万相通用图像编辑（wanx2.1-imageedit）：会保留原物的轮廓、材质和主色，"
            "再按你的需求改造成新物品。每张约 $0.02，按生成张数计费。"
        )

st.title("♻️ 生成式AI旧物创意改造与循环共享平台")


def _run_generation(request: dict, regenerate: bool = False) -> bool:
    """调用图生图并把结果写进 session_state，避免页面一交互就丢失。"""
    progress_bar = st.progress(0.0, text="正在准备…")

    def on_progress(ratio: float, text: str) -> None:
        progress_bar.progress(max(0.0, min(1.0, float(ratio))), text=text)

    try:
        result = generate_remake_images(
            request["image_bytes"],
            request["old_item_desc"],
            request["requirement"],
            request.get("chosen_style", ""),
            count=int(request.get("count", 3)),
            strength=request.get("strength"),
            seed=random.randint(1, 2147483646) if regenerate else request.get("seed"),
            progress=on_progress,
        )
    except Exception as exc:  # 图片损坏、尺寸不合法等
        progress_bar.empty()
        st.error(f"生成失败：{exc}")
        return False

    progress_bar.empty()
    st.session_state["remake"] = result
    return True


# ==================== 页面一：改造工具 ====================
if page == NAV_OPTIONS[0]:
    prefill = st.session_state.pop("prefill", None)
    if prefill:
        st.session_state["f_old"] = prefill.get("old_item", "")
        st.session_state["f_req"] = prefill.get("requirement", "")
        style = prefill.get("style", "")
        if style in STYLE_OPTIONS:
            st.session_state["f_style"] = style
        st.info(f"已载入案例：{prefill.get('old_item', '')} → {prefill.get('requirement', '')}，上传照片即可生成")

    st.caption("上传旧物 → AI生成方案 → 输出教程 → 动手改造 → 分享社区")

    with st.form("remake_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("1️⃣ 上传旧物照片")
            uploaded = st.file_uploader(
                "选择旧物照片（建议正面拍摄、光线充足、主体占画面 2/3）",
                type=["jpg", "jpeg", "png", "webp"],
            )
            if uploaded:
                st.image(uploaded, caption="旧物原图", use_container_width=True)

        with col2:
            st.subheader("2️⃣ 描述旧物与改造需求")
            old_item_desc = st.text_input(
                "旧物描述", key="f_old", placeholder="如：旧牛仔外套"
            )
            requirement = st.text_area(
                "改造需求", key="f_req", placeholder="如：改成猫咪窝，带软垫设计，适合8斤内猫咪"
            )
            chosen_style = st.selectbox("风格偏好（可选）", STYLE_OPTIONS, key="f_style")
            opt1, opt2 = st.columns(2)
            with opt1:
                count = st.slider("生成数量", 1, 4, 3, key="f_count")
            with opt2:
                strength = st.slider(
                    "改造强度",
                    0.3,
                    0.9,
                    0.65,
                    0.05,
                    key="f_strength",
                    help="越大越偏离原物、创意越强；越小越保留原物特征",
                )
            st.caption("提示：改造强度 0.5~0.7 通常最稳；需要大改结构时可调到 0.8 以上")

        submitted = st.form_submit_button("🚀 生成改造方案", type="primary")

    if submitted:
        if not uploaded:
            st.warning("⚠️ 请先上传旧物照片")
        elif not old_item_desc.strip() or not requirement.strip():
            st.warning("⚠️ 请填写旧物描述和改造需求")
        else:
            image_bytes = uploaded.getvalue()
            if len(image_bytes) > config.IMG_MAX_UPLOAD_MB * 1024 * 1024:
                st.error(f"图片超过 {config.IMG_MAX_UPLOAD_MB}MB，请压缩后再上传")
            else:
                request = {
                    "image_bytes": image_bytes,
                    "old_item_desc": old_item_desc.strip(),
                    "requirement": requirement.strip(),
                    "chosen_style": chosen_style,
                    "count": count,
                    "strength": strength,
                    "seed": None,
                }
                st.session_state["last_request"] = request
                st.session_state["share_title"] = f"{old_item_desc.strip()}改造作品"
                st.session_state.pop("remake", None)
                st.session_state.pop("tutorial", None)

                if _run_generation(request):
                    with st.spinner("AI 正在生成实操教程..."):
                        st.session_state["tutorial"] = generate_tutorial(
                            old_item_desc.strip(), requirement.strip(), chosen_style
                        )

    result = st.session_state.get("remake")
    labels = [chr(65 + i) for i in range(len(result.images))] if result else []

    if result:
        st.divider()
        st.subheader("3️⃣ AI 生成的改造效果")
        if result.mode == "api":
            st.success(result.status)
        else:
            st.info(result.status)
        if result.error:
            st.warning(f"接口错误详情：{result.error}")
        for warning in result.warnings:
            st.caption(f"💡 {warning}")

        columns = st.columns(len(result.images))
        for index, (column, image, label) in enumerate(zip(columns, result.images, labels)):
            with column:
                st.image(image, caption=f"方案{label}", use_container_width=True)
                st.download_button(
                    "⬇️ 下载该方案",
                    data=image_to_png_bytes(image),
                    file_name=f"改造方案{label}.png",
                    mime="image/png",
                    key=f"dl_{result.token}_{index}",
                )

        action1, action2, _ = st.columns([1, 1, 2])
        with action1:
            if st.button("🔄 换一批方案", key=f"regen_{result.token}"):
                request = st.session_state.get("last_request")
                if request and _run_generation(request, regenerate=True):
                    st.rerun()
        with action2:
            st.download_button(
                "📦 打包下载全部",
                data=images_to_zip(result.images),
                file_name="改造方案.zip",
                mime="application/zip",
                key=f"zip_{result.token}",
            )

        with st.expander("🔍 本次提示词与调试信息"):
            st.code(result.prompt, language="text")
            st.caption(
                f"模式：{result.mode} · 耗时：{result.elapsed:.1f}s"
                + (f" · task_id：{result.task_id}" if result.task_id else "")
            )
            if result.mode == "demo":
                if result.error:
                    st.caption("演示预览由本地调色生成；本次接口调用失败，可能已产生费用。")
                else:
                    st.caption(
                        "演示预览由本地调色生成，未调用图生图 API、不消耗额度；"
                        "配置 DashScope Key 后会调用 wanx2.1-imageedit 生成真实效果图。"
                    )

    tutorial = st.session_state.get("tutorial")
    if tutorial:
        st.divider()
        st.subheader("4️⃣ 智能实操教程")
        st.markdown(tutorial)
        request = st.session_state.get("last_request") or {}
        st.download_button(
            "📥 下载教程",
            tutorial,
            file_name=f"{request.get('old_item_desc', '旧物')}改造教程.md",
            mime="text/markdown",
            key="dl_tutorial",
        )

        st.divider()
        st.subheader("5️⃣ 分享到社区")
        st.text_input("给作品起个标题", key="share_title")

        share_options = [f"方案{label}" for label in labels]
        if request.get("image_bytes"):
            share_options.append("原图")
        picked = st.radio(
            "选择要发布的图片",
            share_options,
            horizontal=True,
            key=f"share_pick_{result.token if result else 'none'}",
        )
        if st.button("📢 发布到社区广场", type="primary"):
            if picked == "原图" or not result:
                cover = prepare_base_image(request["image_bytes"])
            else:
                cover = result.images[labels.index(picked.replace("方案", ""))]
            publish_work(
                (st.session_state.get("share_title") or "").strip()
                or f"{request.get('old_item_desc', '旧物')}改造作品",
                request.get("requirement", ""),
                request.get("old_item_desc", ""),
                request.get("requirement", ""),
                image_to_jpeg_bytes(cover, max_side=1200),
            )
            st.success("✅ 已发布到社区广场，大家都能看到你的作品啦！")

# ==================== 页面二：案例灵感 ====================
elif page == NAV_OPTIONS[1]:
    st.caption("精选旧物改造案例，获取灵感与参考")

    tag_options = ["衣物", "玻璃", "塑料", "家具", "橡胶", "植物", "宠物", "收纳", "环保", "创意", "户外", "复古风", "北欧风", "简约", "田园风"]
    selected_tags = st.multiselect("按标签筛选（可选）", tag_options)

    if selected_tags:
        shown = recommend_cases(selected_tags, limit=8)
        st.info(f"根据标签「{'、'.join(selected_tags)}」推荐 {len(shown)} 个案例")
    else:
        shown = CASES

    for i in range(0, len(shown), 2):
        columns = st.columns(2)
        for column, case in zip(columns, shown[i : i + 2]):
            with column:
                with st.container(border=True):
                    st.subheader(case["title"])
                    diff_color = {"简单": "green", "中等": "orange", "困难": "red"}.get(case["difficulty"], "gray")
                    st.markdown(
                        f"**旧物**：{case['old_item']}  \n"
                        f"**成品**：{case['result']}  \n"
                        f"**难度**：:{diff_color}[{case['difficulty']}] · **耗时**：{case['time']}"
                    )
                    st.markdown("**标签**：" + " · ".join(f"`{t}`" for t in case["tags"]))
                    with st.expander("查看材料与步骤"):
                        st.write(f"**材料**：{case['materials']}")
                        st.write(f"**步骤**：{case['steps']}")
                    if st.button("用这个案例去改造", key=f"case_{i}_{case['title']}"):
                        st.session_state["prefill"] = {
                            "old_item": case["old_item"],
                            "requirement": case["result"],
                        }
                        st.session_state["nav_to"] = NAV_OPTIONS[0]
                        st.rerun()

# ==================== 页面三：社区广场 ====================
elif page == NAV_OPTIONS[2]:
    tab1, tab2 = st.tabs(["🎨 改造成果", "🔄 闲置置换"])

    with tab1:
        st.subheader("社区改造成果展示")
        works = list_works()
        if not works:
            st.info("社区还没有作品，去「改造工具」生成方案后发布吧！")
        else:
            for work in works:
                with st.container(border=True):
                    col_a, col_b = st.columns([1, 3])
                    with col_a:
                        if work["image"]:
                            st.image(io.BytesIO(work["image"]), width=150)
                        else:
                            st.write("🖼️")
                    with col_b:
                        st.markdown(f"**{work['title']}**")
                        st.caption(f"by {work['author']} · {work['created_at']}")
                        st.write(f"旧物：{work['old_item'] or '-'} → {work['requirement'] or '-'}")
                        c1, c2 = st.columns([1, 4])
                        with c1:
                            if st.button(f"❤️ {work['likes']}", key=f"like_{work['id']}"):
                                like_work(work["id"])
                                st.rerun()

        st.divider()
        st.subheader("📥 快速发布成果")
        with st.form("publish_work_form"):
            pw_title = st.text_input("作品标题")
            pw_old = st.text_input("旧物是什么")
            pw_req = st.text_input("改成了什么")
            pw_img = st.file_uploader("上传成品照片", type=["jpg", "jpeg", "png"])
            if st.form_submit_button("发布作品"):
                if pw_title and pw_old:
                    img_b = pw_img.read() if pw_img else None
                    publish_work(pw_title, pw_req, pw_old, pw_req, img_b)
                    st.success("✅ 发布成功！")
                    st.rerun()
                else:
                    st.warning("请填写标题和旧物")

    with tab2:
        st.subheader("闲置物品置换信息墙")
        exchanges = list_exchanges()
        if not exchanges:
            st.info("暂无置换信息，来发布第一条吧！")
        else:
            for exchange in exchanges:
                with st.container(border=True):
                    st.markdown(f"**{exchange['item_name']}**  ·  `{exchange['category'] or '未分类'}`")
                    st.write(exchange["description"] or "")
                    st.caption(f"联系方式：{exchange['contact']} · {exchange['created_at']}")

        st.divider()
        st.subheader("📥 发布置换信息")
        with st.form("publish_exchange_form"):
            ex_name = st.text_input("物品名称")
            ex_cat = st.selectbox("分类", ["衣物", "家具", "数码", "书籍", "工具", "材料", "其他"])
            ex_desc = st.text_area("物品描述（成色、数量等）")
            ex_contact = st.text_input("联系方式（微信/手机）")
            if st.form_submit_button("发布置换"):
                if ex_name and ex_contact:
                    publish_exchange(ex_name, ex_desc, ex_cat, ex_contact)
                    st.success("✅ 发布成功！")
                    st.rerun()
                else:
                    st.warning("请填写物品名称和联系方式")

st.divider()
st.caption("生成式AI旧物创意改造与循环共享平台 · MVP完整版")
