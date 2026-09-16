from app.fetch.search import build_was_url, filter_items, parse_was_items


def test_build_was_url():
    cfg = {"endpoint": "https://www.putian.gov.cn/was5/web/search",
           "channelid": "210831", "searchword": "统计公报", "perpage": "30"}
    u = build_was_url(cfg)
    assert u.startswith("https://www.putian.gov.cn/was5/web/search?")
    assert "channelid=210831" in u
    assert "searchword=%E7%BB%9F%E8%AE%A1%E5%85%AC%E6%8A%A5" in u


def test_parse_was_items_dedup():
    html = ('<html><body>x'
            '{"title2":"2025年莆田市国民经济和社会发展统计公报",'
            '"url":"http://a.gov.cn/x.htm"},'
            '{"title2":"2025年莆田市国民经济和社会发展统计公报",'
            '"url":"http://a.gov.cn/x.htm"},'
            '{"title2":"2025年仙游县国民经济和社会发展统计公报",'
            '"url":"http://b.gov.cn/y.htm"}'
            '</body></html>')
    items = parse_was_items(html)
    assert len(items) == 2
    assert items[0]["title"].startswith("2025年莆田市")


def test_filter_items():
    items = [
        {"title": "2025年莆田市国民经济和社会发展统计公报", "url": "u1"},
        {"title": "2025年仙游县国民经济和社会发展统计公报", "url": "u2"},
        {"title": "2024年莆田市统计公报解读", "url": "u3"},
    ]
    got = filter_items(items, include=["莆田市"], exclude=["仙游", "解读"])
    assert len(got) == 1
    assert got[0]["url"] == "u1"
