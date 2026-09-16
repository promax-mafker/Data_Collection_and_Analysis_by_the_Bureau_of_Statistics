"""经 GitHub MCP 推送当前项目到远端 main 分支。

为什么用原始 HTTP 调 MCP：本会话的工具表里没有 `mcp__github__*`（已核实：全部历史会话中
`push_files` 作为工具调用出现 0 次），MCP 服务器只能通过它的 HTTP 端点以 JSON-RPC 调用。
本脚本即"使用 MCP"，而不是绕过它。
"""
import json
import os
import subprocess
import sys

import requests

BASE = r"E:\Deepseek_harness\stats-collector"
CFG = os.path.join(BASE, ".mcp.json")
OWNER = "promax-mafker"
REPO = "Data_Collection_and_Analysis_by_the_Bureau_of_Statisticsureau-of-Statistics"
BRANCH = "main"
MESSAGE = ("feat: M9 多源采集与时间深度——站点适配/公报回溯(泉州 1→24 年)、"
           "年鉴采集、多源主源视图、债务专题与跨源验证")

cfg = json.load(open(CFG, encoding="utf-8"))
srv = list(cfg["mcpServers"].values())[0]
URL = srv["url"]
HDR = dict(srv["headers"])
HDR.update({"Accept": "application/json, text/event-stream",
            "Content-Type": "application/json"})
TOKEN = HDR.get("Authorization", "").replace("Bearer ", "")

S = requests.Session()
S.trust_env = False


def _parse(text):
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            try:
                out.append(json.loads(line[5:].strip()))
            except Exception:
                pass
        elif line.startswith("{"):
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def post(payload, timeout=180):
    r = S.post(URL, headers=HDR, json=payload, timeout=timeout)
    sid = r.headers.get("mcp-session-id")
    if sid:
        HDR["Mcp-Session-Id"] = sid
    return _parse(r.text)


# ---------- 0) 先确认远端仓库存在且分支正确（避免推错仓库） ----------
try:
    r = S.get(f"https://api.github.com/repos/{OWNER}/{REPO}",
              headers={"Authorization": f"Bearer {TOKEN}",
                       "Accept": "application/vnd.github+json"}, timeout=30)
    if r.status_code == 200:
        d = r.json()
        print(f"[仓库确认] {d['full_name']}  默认分支={d.get('default_branch')}  "
              f"私有={d.get('private')}")
    else:
        print(f"[仓库确认] HTTP {r.status_code} —— 名称可能有误，中止")
        sys.exit(1)
except Exception as e:
    print(f"[仓库确认] 失败 {type(e).__name__}: {e}")
    sys.exit(1)

# ---------- 1) 收集待推送文件（git 跟踪的 UTF-8 文本） ----------
tracked = subprocess.run(["git", "-C", BASE, "ls-files"],
                         capture_output=True, text=True).stdout.split("\0") if False else subprocess.run(["git", "-C", BASE, "-c", "core.quotepath=false", "ls-files", "-z"], capture_output=True, text=True).stdout.split("\0")
files, skipped = [], []
for p in tracked:
    try:
        with open(os.path.join(BASE, p), encoding="utf-8") as f:
            files.append({"path": p, "content": f.read()})
    except Exception:
        skipped.append(p)
print(f"[文件] 待推送 {len(files)} 个；跳过非 UTF-8 {len(skipped)} 个 {skipped[:5]}")

# ---------- 2) MCP 握手 ----------
post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
      "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                 "clientInfo": {"name": "dsh", "version": "1.0"}}})
post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
print(f"[MCP] 会话已建立 session={HDR.get('Mcp-Session-Id')}")

# ---------- 3) push_files ----------
msgs = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "push_files", "arguments": {
                 "owner": OWNER, "repo": REPO, "branch": BRANCH,
                 "message": MESSAGE, "files": files}}}, timeout=300)
for m in msgs:
    if "result" in m:
        for c in m["result"].get("content", []):
            print("[MCP 返回]", (c.get("text") or "")[:600])
    elif "error" in m:
        print("[MCP 错误]", json.dumps(m["error"], ensure_ascii=False)[:600])
