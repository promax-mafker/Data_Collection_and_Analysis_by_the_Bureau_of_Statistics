"""industry_classify.py 测试：企业名称关键词 → 行业大类。"""
from app.parse.industry_classify import classify, classify_batch


def test_known_industries():
    cases = {
        "福建利瑶纺织制衣有限公司": "纺织鞋服",
        "卡尔美体育用品有限公司": "纺织鞋服",  # 体育用品→鞋服(泉州语境)
        "泉州市汉威机械制造有限公司": "机械装备",
        "福建科立讯通信有限公司": "电子信息",
        "泉州银行股份有限公司": "金融",
        "泉州华星燃气有限公司": "石油化工",
        "福建爱乡亲食品股份有限公司": "健康食品",
        "晋江市港益纤维制品有限公司": "新材料",  # 纤维制品→新材料(特异性优先)
        "耀华园林股份有限公司": "建筑园林",
        "泉州天娇妇幼卫生用品有限公司": "卫生用品",
    }
    for name, expect in cases.items():
        industry, method = classify(name)
        assert industry == expect, f"{name} → {industry}，期望 {expect}"
        assert method == "rule"


def test_unknown_returns_unknown():
    industry, method = classify("某某神秘企业")
    assert industry == "其他"
    assert method == "unknown"


def test_batch_classify_counts():
    names = ["泉州银行股份有限公司", "福建利瑶纺织制衣有限公司", "神秘公司", "泉州市汉威机械制造有限公司"]
    rows = classify_batch([(i + 1, n) for i, n in enumerate(names)])
    assert len(rows) == 4
    by_id = {r["enterprise_id"]: r for r in rows}
    assert by_id[1]["industry"] == "金融"
    assert by_id[2]["industry"] == "纺织鞋服"
    assert by_id[3]["method"] == "unknown"
    assert by_id[4]["industry"] == "机械装备"


def test_specific_keyword_priority():
    """特异性词优先：纤维制品应归新材料而非纺织。"""
    industry, _ = classify("某纤维制品科技有限公司")
    assert industry == "新材料"
