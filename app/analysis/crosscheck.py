"""跨源一致性状态（M9d 起点）。

回答一个具体问题：**每个关键指标，除了统计局口径，是否还有独立第二来源？**

依据设计 P5：**同源搬运不算交叉验证** —— 统计公报与统计年鉴都出自统计局，
彼此印证不能抗数据美化；只有**编制主体不同**的来源（财政部债券平台、海关）
才算独立。

没有独立第二来源的指标，必须在报告里显式标注「单一来源、不可交叉验证」，
而不是让它看起来和已验证指标一样可靠。
"""
# 编制主体与统计局不同的来源 → 才算独立口径
INDEPENDENT_KINDS = {"celma": "财政部地方政府债券平台", "customs": "海关"}
# 同源（均为统计局口径）
SAME_ORIGIN_KINDS = {"": "统计公报", "bulletin": "统计公报", "yearbook": "统计年鉴"}

KEY_INDICATORS = ["地区生产总值", "进出口总额", "一般公共预算收入",
                  "常住人口", "居民消费价格指数", "社会消费品零售总额"]


def cross_source_status(repo, region="泉州市", indicators=None):
    """逐指标判定来源独立性 → ``[{indicator, kinds, independent, verdict, note}]``。

    verdict：

    * ``ok``            —— 存在**独立口径**第二来源，可交叉验证
    * ``single_source`` —— 只有统计局口径来源，**不可抗美化**
    * ``na``            —— 无数据
    """
    indicators = indicators or KEY_INDICATORS
    rows = repo.query_data(region=region, primary_only=False)
    by_ind = {}
    for r in rows:
        name = r.get("indicator_name")
        if name not in indicators:
            continue
        kind = (r.get("source_kind") or "")
        by_ind.setdefault(name, set()).add(kind)

    out = []
    for name in indicators:
        kinds = by_ind.get(name, set())
        independent = sorted(k for k in kinds if k in INDEPENDENT_KINDS)
        if not kinds:
            out.append({"indicator": name, "kinds": [], "independent": [],
                        "verdict": "na", "note": "无数据"})
        elif independent:
            out.append({"indicator": name, "kinds": sorted(kinds),
                        "independent": independent, "verdict": "ok",
                        "note": "独立口径：" + "、".join(INDEPENDENT_KINDS[k]
                                                        for k in independent)})
        else:
            labels = sorted(SAME_ORIGIN_KINDS.get(k, k) for k in kinds)
            out.append({"indicator": name, "kinds": sorted(kinds), "independent": [],
                        "verdict": "single_source",
                        "note": f"仅统计局口径（{'、'.join(labels)}）—— 不可交叉验证，"
                                "引用时须标注单一来源"})
    return out


def summarize_cross_source(status):
    """汇总 → ``{ok, single_source, na, single_list}``（供报告/决策树直接使用）。"""
    counts = {"ok": 0, "single_source": 0, "na": 0}
    single = []
    for s in status:
        counts[s["verdict"]] = counts.get(s["verdict"], 0) + 1
        if s["verdict"] == "single_source":
            single.append(s["indicator"])
    return {"ok": counts["ok"], "single_source": counts["single_source"],
            "na": counts["na"], "single_list": single}
