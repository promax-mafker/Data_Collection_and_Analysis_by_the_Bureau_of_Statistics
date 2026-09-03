from app.fetch.parser import extract_links, extract_title, extract_text, hash_text

HTML = """<html><head><title>福建省统计局</title></head><body>
<a href="/xxgk/tjgb/">统计公报</a>
<a href="https://tjj.fuzhou.gov.cn/">福州市统计局</a>
<script>var x=1;</script>
<p>全年地区生产总值53162.36亿元。</p>
</body></html>"""

def test_extract_links_absolute_and_text():
    links = extract_links(HTML, "https://tjj.fujian.gov.cn/")
    assert ("https://tjj.fujian.gov.cn/xxgk/tjgb/", "统计公报") in links
    assert ("https://tjj.fuzhou.gov.cn/", "福州市统计局") in links

def test_extract_title():
    assert extract_title(HTML) == "福建省统计局"

def test_extract_text_removes_script():
    text = extract_text(HTML)
    assert "地区生产总值53162.36亿元" in text
    assert "var x" not in text

def test_hash_deterministic():
    assert hash_text("abc") == hash_text("abc")
    assert len(hash_text("abc")) == 64
