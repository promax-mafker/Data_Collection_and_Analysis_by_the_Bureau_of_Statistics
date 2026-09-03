import hashlib
import re
from urllib.parse import urljoin
from bs4 import BeautifulSoup

def extract_links(html: str, base_url: str):
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        out.append((urljoin(base_url, href), a.get_text(" ", strip=True)))
    return out

def extract_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    t = soup.find("title")
    return t.get_text(strip=True) if t else ""

def extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    return re.sub(r"\n{2,}", "\n", text)

def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
