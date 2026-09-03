import json
import os
from _mcp_client import MCPClient

OWNER = "promax-mafker"
REPO = "Data_Collection_and_Analysis_by_the_Bureau_of_Statisticsureau-of-Statistics"
BRANCH = "main"
MESSAGE = "feat: 统计局数据采集平台初始提交（递进发现/采集/规则抽取/分类入库/Web 管理界面）"

BASE = os.path.dirname(os.path.abspath(__file__))
EXCLUDE_DIRS = {".git", ".venv", "data", "__pycache__", ".pytest_cache"}
EXCLUDE_FILES = {".mcp.json", "_mcp_probe.py", "_mcp_client.py", "_mcp_list.py", "_mcp_repo_check.py"}

files = []
for root, dirs, names in os.walk(BASE):
    dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
    for n in names:
        if n in EXCLUDE_FILES:
            continue
        full = os.path.join(root, n)
        rel = os.path.relpath(full, BASE).replace(os.sep, "/")
        with open(full, "r", encoding="utf-8") as fh:
            content = fh.read()
        files.append({"path": rel, "content": content})
files.sort(key=lambda x: x["path"])

print("files to push:", len(files))
for f in files:
    print(" ", f["path"])

c = MCPClient()
st, evs = c.initialize()
st, evs = c.call_tool("push_files", {
    "owner": OWNER, "repo": REPO, "branch": BRANCH,
    "files": files, "message": MESSAGE,
})
with open("data/_push_result.json", "w", encoding="utf-8") as fh:
    fh.write(json.dumps(evs, ensure_ascii=False, indent=1))
print("push status:", st)
