import time
import requests
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from .parser import decode_html

class FetchError(Exception):
    pass

class HttpClient:
    def __init__(self, timeout=30, retries=2, delay=1.0, user_agent=None, respect_robots=True, verify=True):
        self.timeout = timeout
        self.retries = retries
        self.delay = delay
        self.user_agent = user_agent or "Mozilla/5.0 (compatible; stats-collector/1.0)"
        self.respect_robots = respect_robots
        self.verify = verify  # 部分政府站证书自签名，采集时允许 False
        self._robots_cache = {}   # netloc -> RobotFileParser | None(fail-open)

    def _allowed(self, url) -> bool:
        """robots 判定：按站点缓存；首次用带超时的 requests 读取；失败 fail-open。"""
        if not self.respect_robots:
            return True
        host = urlparse(url).netloc
        rp = self._robots_cache.get(host)
        if rp is None and host not in self._robots_cache:
            try:
                r = requests.get(f"{urlparse(url).scheme}://{host}/robots.txt",
                                 timeout=6, headers={"User-Agent": self.user_agent})
                rp = RobotFileParser()
                rp.parse(r.text.splitlines())
            except Exception:
                rp = None  # fail-open：robots 不可读时不阻断抓取
            self._robots_cache[host] = rp
        rp = self._robots_cache.get(host)
        if rp is None:
            return True
        return rp.can_fetch(self.user_agent, url)

    def _get_raw(self, url: str) -> requests.Response:
        last = None
        for attempt in range(self.retries + 1):
            try:
                resp = requests.get(url, timeout=self.timeout, verify=self.verify,
                                    headers={"User-Agent": self.user_agent})
                resp.raise_for_status()
                time.sleep(self.delay)
                return resp
            except requests.RequestException as e:
                last = e
                time.sleep(2 ** attempt)
        raise FetchError(f"抓取失败 {url}: {last}")

    def get(self, url: str) -> str:
        """抓取并统一解码为文本。"""
        if not self._allowed(url):
            raise FetchError(f"robots 禁止访问: {url}")
        return decode_html(self._get_raw(url).content)

    def download(self, url: str) -> bytes:
        """下载原始字节（PDF / 其它二进制）"""
        if not self._allowed(url):
            raise FetchError(f"robots 禁止访问: {url}")
        return self._get_raw(url).content
