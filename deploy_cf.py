#!/usr/bin/env python3
"""cfnew 自动部署：把仓库 _worker.js 推到 Cloudflare Worker。
安全特性：
- 部署前 GET 现有 settings，原样重放 bindings(KV/变量)与兼容日期，配置零丢失
- 若发现 secret 类型绑定（值不可读，重放会丢）→ 立即中止并报错，绝不静默删密钥
- 与线上代码 sha256 相同则跳过，不制造垃圾版本
"""
import os, sys, json, hashlib, urllib.request, urllib.error

TOK = os.environ["CF_API_TOKEN"]
ACCT = os.environ["CF_ACCOUNT_ID"]
NAME = os.environ.get("CF_SCRIPT_NAME") or "cfnew"
BASE = f"https://api.cloudflare.com/client/v4/accounts/{ACCT}/workers/scripts/{NAME}"
HDR = {"Authorization": f"Bearer {TOK}", "Accept": "application/json"}


def api(url, data=None, headers=None, method=None):
    req = urllib.request.Request(url, data=data, headers=headers or dict(HDR), method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as f:
            return f.read()
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode(errors='replace')[:800]}", file=sys.stderr)
        sys.exit(1)


# 1) 读仓库新代码
code = open("_worker.js", "rb").read()
new_sha = hashlib.sha256(code).hexdigest()
print(f"仓库 _worker.js sha256={new_sha[:16]} size={len(code)}")

# 2) 读线上当前代码，相同则跳过
online = api(BASE, headers={**HDR, "Accept": "*/*"}).decode("utf-8", errors="replace")
if hashlib.sha256(online.encode()).hexdigest() == new_sha:
    print("SKIP: 线上代码与仓库一致，无需部署")
    sys.exit(0)

# 3) 读线上 settings，重放绑定
s = json.loads(api(BASE + "/settings"))["result"]
bindings = []
for b in s.get("bindings", []):
    t = b.get("type")
    if t == "kv_namespace":
        bindings.append({"type": "kv_namespace", "name": b["name"], "namespace_id": b["namespace_id"]})
    elif t == "plain_text":
        bindings.append({"type": "plain_text", "name": b["name"], "value": b.get("value", "")})
    elif t in ("secret_text", "secret_bytes"):
        print(f"ABORT: 绑定 {b['name']} 是 secret，API 读不到值，重放会丢失。"
              f"请改用 KV/面板配置，或手动在 CF 后台补回后再跑。", file=sys.stderr)
        sys.exit(2)
    else:
        bindings.append(b)
compat = s.get("compatibility_date") or "2026-01-20"
print(f"保留绑定: {[ (b['type'], b['name']) for b in bindings ]} compat={compat}")

# 4) 上传新版本
meta = {
    "main_module": "_worker.js",
    "compatibility_date": compat,
    "bindings": bindings,
    "usage_model": s.get("usage_model") or "standard",
}
bd = "----minisCfBoundary7f3a"
body = (
    f"--{bd}\r\nContent-Disposition: form-data; name=\"metadata\"\r\n"
    f"Content-Type: application/json\r\n\r\n{json.dumps(meta)}\r\n"
    f"--{bd}\r\nContent-Disposition: form-data; name=\"_worker.js\"; "
    f"filename=\"_worker.js\"\r\nContent-Type: application/javascript+module\r\n\r\n"
).encode() + code + f"\r\n--{bd}--\r\n".encode()

r = json.loads(api(BASE, data=body, headers={**HDR, "Content-Type": f"multipart/form-data; boundary={bd}"}, method="PUT"))
if not r.get("success"):
    print(f"DEPLOY FAILED: {r.get('errors')}", file=sys.stderr)
    sys.exit(3)
print(f"DEPLOYED ✅ version={r.get('result', {}).get('version_id', '?')}")
