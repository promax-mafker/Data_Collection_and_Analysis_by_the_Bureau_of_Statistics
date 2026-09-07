"""LLM 客户端：OpenAI 兼容 chat/completions 调用（读 .env，支持 JSON 输出）。"""
import json
import os
import re

import requests
from dotenv import load_dotenv

load_dotenv()  # 项目根 .env


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(self, base_url=None, api_key=None, model=None, temperature=0.2, timeout=180, retries=1):
        self.base_url = (base_url or os.environ.get("LLM_BASE_URL", "")).rstrip("/")
        self.api_key = api_key or os.environ.get("LLM_API_KEY", "")
        self.model = model or os.environ.get("LLM_MODEL", "")
        self.temperature = temperature
        self.timeout = timeout
        self.retries = retries

    @property
    def enabled(self) -> bool:
        """key/base/model 任一缺失则视为未启用（降级路径）。"""
        return bool(self.api_key and self.base_url and self.model)

    def complete_json(self, system: str, user: str, temperature=None) -> dict:
        """请求 JSON 输出并解析；任何失败抛 LLMError。"""
        if not self.enabled:
            raise LLMError("LLM 未启用（缺 base_url/api_key/model）")
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": 2000,
        }
        last = None
        for attempt in range(self.retries + 1):
            try:
                resp = requests.post(
                    url, json=payload, timeout=self.timeout,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    proxies={"http": None, "https": None})
                if resp.status_code != 200:
                    raise LLMError(f"HTTP {resp.status_code}: {resp.text[:300]}")
                try:
                    content = resp.json()["choices"][0]["message"]["content"]
                except (KeyError, IndexError, ValueError) as e:
                    raise LLMError(f"响应结构异常: {e} | {resp.text[:300]}")
                return self._parse_json(content)
            except LLMError:
                raise
            except requests.RequestException as e:
                last = LLMError(f"请求失败(超时/网络): {e}")
        raise last

    @staticmethod
    def _parse_json(content: str) -> dict:
        """剥离 ```json 围栏后解析；失败抛 LLMError。"""
        text = content.strip()
        m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
        if m:
            text = m.group(1).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMError(f"无法解析 JSON 输出: {e} | 原文前300字: {text[:300]}")
