import streamlit as st
from PIL import Image
from io import BytesIO
import config
from ai_img2img import generate_remake_images
from ai_tutorial import generate_tutorial
from community import init_db, publish_work, list_works, like_work, publish_exchange, list_exchanges
from cases import CASES, recommend_cases

init_db()

st.set_page_config(page_title="旧物创意改造平台", page_icon="♻️", layout="wide")

page = st.sidebar.selectbox("📍 功能导航", ["🛠️ 改造工具", "📚 案例灵感", "🌐 社区广场"])

with st.sidebar:
    st.divider()
    st.header("⚙️ API 配置")
    st.caption("直接粘贴key即可，无需设环境变量")
    img_key = st.text_input("图生图 Key（DashScope）", type="password", placeholder="粘贴阿里云DashScope key")
    llm_key = st.text_input("LLM Key（DeepSeek）", type="password", placeholder="粘贴DeepSeek key")
    if img_key:
        config.DASHSCOPE_API_KEY = img_key
    if llm_key:
        config.DEEPSEEK_API_KEY = llm_key
    img_ok = bool(config.DASHSCOPE_API_KEY)
    llm_ok = bool(config.DEEPSEEK_API_KEY)
    st.write(f"图生图API: {'✅ 已配置' if img_ok else '❌ 演示模式'}")
    st.write(f"LLM API: {'✅ 已配置' if llm_ok else '❌ 演示模式'}")

st.title("♻️ 生成式AI旧物创意改造与循环共享平台")

# ==================== 页面一：改造工具 ====================
if page == "🛠️ 改造工具":
    st.caption("上传旧物 → AI生成方案 → 输出教程 → 动手改造 → 分享社区")

    with st.form("remake_form", clear_on_submit=False):
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("1️⃣ 上传旧物照片")
            uploaded = st.file_uploader("选择旧物照片", type=["jpg", "jpeg", "png"])
            if uploaded:
                st.image(uploaded, caption="旧物原图", use_container_width=True)

        with col2:
            st.subheader("2️⃣ 描述旧物与改造需求")
            old_item_desc = st.text_input("旧物描述", placeholder="如：旧牛仔外套")
            requirement = st.text_area(
                "改造需求", placeholder="如：改成猫咪窝，带软垫设计，适合8斤内猫咪"
            )
            style_options = ["", "简约北欧风", "日式原木风", "工业风", "复古风", "可爱卡通风"]
            chosen_style = st.selectbox("风格偏好（可选）", style_options)

        submitted = st.form_submit_button("🚀 生成改造方案", type="primary")

    if submitted:
        if not uploaded:
            st.warning("⚠️ 请先上传旧物照片")
        elif not old_item_desc.strip() or not requirement.strip():
            st.warning("⚠️ 请填写旧物描述和改造需求")
        else:
            with st.spinner("AI正在生成改造效果（约10-30秒）..."):
                images, img_status = generate_remake_images(old_item_desc, requirement, count=3)

            st.info(img_status)
            if images:
                st.subheader("3️⃣ AI生成的改造效果")
                cols = st.columns(3)
                captions = ["方案A", "方案B", "方案C"]
                for col, img, cap in zip(cols, images, captions):
                    with col:
                        st.image(img, caption=cap, use_container_width=True)

            with st.spinner("AI正在生成实操教程..."):
                tutorial = generate_tutorial(old_item_desc, requirement, chosen_style)

            if tutorial:
                st.subheader("4️⃣ 智能实操教程")
                st.markdown(tutorial)
                st.download_button(
                    "📥 下载教程",
                    tutorial,
                    file_name=f"{old_item_desc}改造教程.md",
                    mime="text/markdown",
                )

                st.divider()
                st.subheader("5️⃣ 分享到社区")
                share_title = st.text_input("给作品起个标题", value=f"{old_item_desc}改造作品")
                if st.button("📢 发布到社区广场"):
                    img_bytes = None
                    if uploaded:
                        uploaded.seek(0)
                        img_bytes = uploaded.read()
                    publish_work(share_title, requirement, old_item_desc, requirement, img_bytes)
                    st.success("✅ 已发布到社区广场，大家都能看到你的作品啦！")

# ==================== 页面二：案例灵感 ====================
elif page == "📚 案例灵感":
    st.caption("精选旧物改造案例，获取灵感与参考")

    tag_options = ["衣物", "玻璃", "塑料", "家具", "橡胶", "植物", "宠物", "收纳", "环保", "创意", "户外", "复古风", "北欧风", "简约", "田园风"]
    selected_tags = st.multiselect("按标签筛选（可选）", tag_options)

    if selected_tags:
        shown = recommend_cases(selected_tags, limit=8)
        st.info(f"根据标签「{'、'.join(selected_tags)}」推荐 {len(shown)} 个案例")
    else:
        shown = CASES

    for i in range(0, len(shown), 2):
        cols = st.columns(2)
        for col, case in zip(cols, shown[i : i + 2]):
            with col:
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
                    if st.button(f"用这个案例去改造", key=f"case_{i}_{case['title']}"):
                        st.session_state["case_pick"] = case
                        st.switch_page("app.py")

# ==================== 页面三：社区广场 ====================
elif page == "🌐 社区广场":
    tab1, tab2 = st.tabs(["🎨 改造成果", "🔄 闲置置换"])

    with tab1:
        st.subheader("社区改造成果展示")
        works = list_works()
        if not works:
            st.info("社区还没有作品，去「改造工具」生成方案后发布吧！")
        else:
            for w in works:
                with st.container(border=True):
                    col_a, col_b = st.columns([1, 3])
                    with col_a:
                        if w["image"]:
                            st.image(BytesIO(w["image"]), width=150)
                        else:
                            st.write("🖼️")
                    with col_b:
                        st.markdown(f"**{w['title']}**")
                        st.caption(f"by {w['author']} · {w['created_at']}")
                        st.write(f"旧物：{w['old_item']} → {w['requirement']}")
                        c1, c2 = st.columns([1, 4])
                        with c1:
                            if st.button(f"❤️ {w['likes']}", key=f"like_{w['id']}"):
                                like_work(w["id"])
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
            for e in exchanges:
                with st.container(border=True):
                    st.markdown(f"**{e['item_name']}**  ·  `{e['category'] or '未分类'}`")
                    st.write(e["description"] or "")
                    st.caption(f"联系方式：{e['contact']} · {e['created_at']}")

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
