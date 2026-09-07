"""企业名称 → 行业大类归类（规则关键词，特异性优先；LLM 兜底在采集层）。"""
import re

# (行业, [关键词]) —— 顺序即优先级：特异性高（新材料/卫生用品）在前，避免被宽泛词抢先
INDUSTRY_KEYWORDS = [
    ("卫生用品", ["卫生用品", "妇幼", "纸业"]),
    ("新材料", ["新材料", "材料科技", "纤维制品"]),
    ("金融", ["银行", "融资租赁", "小额贷款", "供应链管理", "供应链金融", "担保"]),
    ("电子信息", ["电子", "通信", "通讯", "光电", "半导体", "物联网", "科技", "智能"]),
    ("机械装备", ["机械", "智能装备", "机电", "汽配", "汽车", "模具", "装备"]),
    ("石油化工", ["石化", "化工", "燃气"]),
    ("环保公用", ["环保", "供水", "水务"]),
    ("建筑园林", ["建设", "园林", "城市规划", "规划设计"]),
    ("建材家居", ["建材", "陶瓷", "卫浴", "石材", "家居", "管业"]),
    ("健康食品", ["食品", "茶业", "水产", "饮料", "生物科技"]),
    ("纺织鞋服", ["纺织", "制衣", "鞋", "服装", "纤维", "皮革", "皮业", "服饰", "体育用品", "轻工"]),
]


def classify(name: str):
    """返回 (industry, method)。命中规则 → method='rule'；否则 ('其他','unknown')。"""
    name = name or ""
    for industry, kws in INDUSTRY_KEYWORDS:
        for kw in kws:
            if kw in name:
                return industry, "rule"
    return "其他", "unknown"


def classify_batch(enterprises):
    """enterprises: list[(enterprise_id, name)] → list[dict(enterprise_id, industry, method)]。"""
    out = []
    for eid, name in enterprises:
        industry, method = classify(name)
        out.append({"enterprise_id": eid, "industry": industry, "method": method})
    return out
