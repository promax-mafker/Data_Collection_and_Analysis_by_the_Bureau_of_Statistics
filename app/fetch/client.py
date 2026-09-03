import time
import requests
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

class FetchError(Exception):
    pass

class HttpClient:
    def __init__(self, timeout=20, retries=2, delay=1.0, user_agent=None, respect_robots=True):
        self.timeout = timeout
        self.retries = retries
        self.delay = delay
        self.user_agent = user_agent or "Mozilla/5.0 (compatible; stats-collector/1.0)"
        self.respect_robots = respect_robots

    def _allowed(self, url) -> bool:
        if not self.respect_robots:
            return True
        try:
            p = urlparse(url)
            rp = RobotFileParser()
            rp.set_url(f"{p.scheme}://{p.netloc}/robots.txt")
            rp.read()
            return rp.can_fetch(self.user_agent, url)
        except Exception:
            return True

    def get(self, url: str) -> str:
        if not self._allowed(url):
            raise FetchError(f"robots 禁止访问: {url}")
        last = None
        for attempt in range(self.retries + 1):
            try:
                resp = requests.get(url, timeout=self.timeout,
                                    headers={"User-Agent": self.user_agent})
                resp.raise_for_status()
                resp.encoding = resp.apparent_encoding or resp.encoding
                time.sleep(self.delay)
                return resp.text
            except requests.RequestException as e:
                last = e
                time.sleep(2 ** attempt)
        raise FetchError(f"抓取失败 {url}: {last}")
