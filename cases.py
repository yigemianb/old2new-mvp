CASES = [
    {
        "title": "旧牛仔外套 → 猫咪窝",
        "old_item": "旧牛仔外套",
        "result": "北欧风猫咪窝，带软垫设计",
        "difficulty": "简单",
        "time": "约1小时",
        "tags": ["衣物", "宠物", "北欧风"],
        "steps": "裁剪成型 → 缝合主体 → 填充软垫 → 封口缝合 → 装饰细节",
        "materials": "牛仔外套、针线、填充棉、软垫布",
    },
    {
        "title": "旧玻璃瓶 → 多肉花盆",
        "old_item": "玻璃瓶/罐头瓶",
        "result": "透明多肉花盆，麻绳田园装饰",
        "difficulty": "简单",
        "time": "约30分钟",
        "tags": ["玻璃", "植物", "田园风"],
        "steps": "清洗去标 → 缠绕麻绳 → 铺底石 → 填土 → 种入多肉",
        "materials": "玻璃瓶、麻绳、热熔胶、底石、营养土、多肉植物",
    },
    {
        "title": "旧T恤 → 环保购物袋",
        "old_item": "旧T恤",
        "result": "无缝环保购物袋，可水洗",
        "difficulty": "简单",
        "time": "约20分钟",
        "tags": ["衣物", "日用", "环保"],
        "steps": "裁剪袖口领口 → 底部剪流苏 → 交替打结 → 拉紧定型",
        "materials": "旧T恤、剪刀",
    },
    {
        "title": "旧木抽屉 → 墙面置物架",
        "old_item": "旧木抽屉",
        "result": "复古墙面置物架，可挂可放",
        "difficulty": "中等",
        "time": "约2小时",
        "tags": ["家具", "收纳", "复古风"],
        "steps": "打磨去漆 → 上色刷漆 → 装挂钩 → 上墙固定 → 摆放装饰",
        "materials": "木抽屉、砂纸、油漆、画笔、挂钩、螺丝",
    },
    {
        "title": "旧CD盒 → 首饰收纳架",
        "old_item": "旧CD盒",
        "result": "透明多层首饰展示架",
        "difficulty": "简单",
        "time": "约40分钟",
        "tags": ["塑料", "收纳", "简约"],
        "steps": "拆解盒体 → 层叠粘合 → 加隔板分区 → 斜靠摆放",
        "materials": "CD盒若干、强力胶、硬纸板隔板",
    },
    {
        "title": "旧轮胎 → 花园坐凳",
        "old_item": "旧轮胎",
        "result": "彩色花园坐凳，可坐可储物",
        "difficulty": "中等",
        "time": "约3小时",
        "tags": ["橡胶", "家具", "户外"],
        "steps": "清洗脱脂 → 上色喷涂 → 叠放固定 → 加坐垫 → 放置花园",
        "materials": "旧轮胎、喷漆、螺栓、圆形坐垫",
    },
    {
        "title": "旧键盘 → 复古冰箱贴",
        "old_item": "旧机械键盘键帽",
        "result": "字母冰箱贴拼字留言",
        "difficulty": "简单",
        "time": "约15分钟",
        "tags": ["塑料", "装饰", "创意"],
        "steps": "拆下键帽 → 背面贴磁铁 → 拼字上冰箱",
        "materials": "旧键帽、小磁铁片、强力胶",
    },
    {
        "title": "旧灯泡 → 微缩花瓶",
        "old_item": "坏白炽灯泡",
        "result": "透明水培花瓶挂饰",
        "difficulty": "中等",
        "time": "约45分钟",
        "tags": ["玻璃", "植物", "创意"],
        "steps": "小心拆芯 → 清洗内部 → 穿铁丝挂绳 → 注水插花",
        "materials": "坏灯泡、铁丝、钳子、手套、水培植物",
    },
]


def recommend_cases(tags, limit=3):
    if not tags:
        return CASES[:limit]
    scored = []
    for case in CASES:
        score = len(set(tags) & set(case["tags"]))
        scored.append((score, case))
    scored.sort(key=lambda x: -x[0])
    matched = [c for s, c in scored if s > 0]
    return (matched + CASES)[:limit]
