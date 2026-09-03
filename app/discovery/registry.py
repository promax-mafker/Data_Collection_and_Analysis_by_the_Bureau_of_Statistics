import yaml

class Registry:
    def __init__(self, seeds, province_anchor, expected_cities, known_domains, bulletin_keywords, exclude_domains=None):
        self.seeds = seeds
        self.province_anchor = province_anchor
        self.expected_cities = expected_cities
        self.known_domains = known_domains
        self.bulletin_keywords = bulletin_keywords
        self.exclude_domains = exclude_domains or []

    @classmethod
    def load(cls, path):
        with open(path, "r", encoding="utf-8") as f:
            d = yaml.safe_load(f)
        return cls(
            seeds=d.get("seeds", []),
            province_anchor=d.get("province_anchor", ""),
            expected_cities=d.get("expected_cities", []),
            known_domains=d.get("known_domains", []),
            bulletin_keywords=d.get("bulletin_keywords", []),
            exclude_domains=d.get("exclude_domains", []),
        )
