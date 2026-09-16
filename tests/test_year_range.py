from app.fetch.bulletins import in_year_range, parse_year_range


def test_parse_year_range():
    assert parse_year_range("2015-2025") == (2015, 2025)
    assert parse_year_range("2020") == (2020, 2020)
    assert parse_year_range("") is None
    assert parse_year_range(None) is None


def test_in_year_range():
    assert in_year_range("2024", (2015, 2025)) is True
    assert in_year_range("2007", (2015, 2025)) is False
    assert in_year_range("2024", None) is True        # 未配置 = 不过滤（向后兼容）
    assert in_year_range("", (2015, 2025)) is False   # 年份未识别 → 不采（宁可缺）
    assert in_year_range("abc", (2015, 2025)) is False
