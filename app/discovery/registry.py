import os

import yaml

from ..fetch.adapters import AdapterRegistry


class Registry:
    def __init__(self, seeds, province_anchor, expected_cities, known_domains, bulletin_keywords,
                 exclude_domains=None, manual_bureaus=None, adapters=None):
        self.seeds = seeds
        self.province_anchor = province_anchor
        self.expected_cities = expected_cities
        self.known_domains = known_domains
        self.bulletin_keywords = bulletin_keywords
        self.exclude_domains = exclude_domains or []
        self.manual_bureaus = manual_bureaus or []
        self.adapters = adapters if adapters is not None else AdapterRegistry([])

    @classmethod
    def load(cls, path, adapter_path=None):
        """加载机构配置；同时挂载站点适配库（M9a）。

        ``adapter_path`` 缺省时自动取与 `bureaus.yaml` **同目录**的
        `site_adapters.yaml`（存在才加载）。这样所有既有调用点
        （`run.py` / `app/main.py` / `quanzhou.py` / 测试）无需改动即可获得适配能力；
        文件缺失时退化为空适配库，行为与 M9a 之前一致。
        """
        with open(path, "r", encoding="utf-8") as f:
            d = yaml.safe_load(f)
        if adapter_path is None:
            sibling = os.path.join(os.path.dirname(os.path.abspath(path)), "site_adapters.yaml")
            adapter_path = sibling if os.path.exists(sibling) else None
        adapters = AdapterRegistry.load(adapter_path) if adapter_path else AdapterRegistry([])
        return cls(
            seeds=d.get("seeds", []),
            province_anchor=d.get("province_anchor", ""),
            expected_cities=d.get("expected_cities", []),
            known_domains=d.get("known_domains", []),
            bulletin_keywords=d.get("bulletin_keywords", []),
            exclude_domains=d.get("exclude_domains", []),
            manual_bureaus=d.get("manual_bureaus", []),
            adapters=adapters,
        )

    def manual_cfg(self, bureau):
        """按机构名返回手工配置（含 bulletin_search 等），无则 None"""
        for m in self.manual_bureaus:
            if m.get("name") == bureau.name:
                return m
        return None

    def adapter_for(self, region):
        """按地区取站点适配，无则 None。"""
        return self.adapters.for_region(region) if self.adapters else None
