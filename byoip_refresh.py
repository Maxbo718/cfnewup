# 自动生成：CF 借壳段(BYOIP)在线清单，每周一由 GitHub Actions 刷新
# 流程: he.net实时路由表(AS13335) − CF官方ips-v4 → 按/16族抽样 → HTTP探活(/cdn-cgi/trace) → ip-api城市标注
import re, json, ipaddress, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)'}

def get(url, data=None, headers=None, timeout=40):
    h = dict(UA)
    if headers: h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h)
    return urllib.request.urlopen(req, timeout=timeout).read()

# 1) 官方14段
off = [ipaddress.ip_network(l.strip()) for l in get('https://www.cloudflare.com/ips-v4').decode().splitlines() if '/' in l]
print(f'官方段: {len(off)}')

# 2) AS13335 广播全表
html = get('https://bgp.he.net/AS13335', timeout=90).decode('utf-8', 'ignore')
prefixes = sorted(set(re.findall(r'/net/(\d{1,3}(?:\.\d{1,3}){3}/\d{1,2})"', html)))
nets = [ipaddress.ip_network(p) for p in prefixes]
byo = [n for n in nets if not any(n.subnet_of(o) for o in off)]
print(f'广播前缀: {len(nets)} → 借壳段: {len(byo)}')

# 3) 按 /16 族去重，每族取最小的一个前缀抽样 IP
fam = {}
for n in sorted(byo, key=lambda x: int(x.network_address)):
    fam.setdefault('.'.join(str(n).split('.')[:2]), n)
samples = []
for k, n in fam.items():
    base = n.network_address
    ip = str(base + min(50, n.num_addresses - 2))
    samples.append((str(n), ip))
print(f'去重族数: {len(samples)}')

# 4) HTTP 探活（必须是能返回 trace 的 CF 边缘）
def alive(item):
    pfx, ip = item
    try:
        t = get(f'http://{ip}/cdn-cgi/trace', timeout=8).decode('utf-8', 'ignore')
        m = re.search(r'colo=(\w+)', t)
        return (pfx, ip, m.group(1)) if 'colo=' in t else None
    except Exception:
        return None

with ThreadPoolExecutor(20) as pool:
    ok = [r for r in pool.map(alive, samples) if r]
print(f'边缘存活: {len(ok)}')

# 5) ip-api 批量城市标注（每次最多100）
def geo(ips):
    out = {}
    for i in range(0, len(ips), 100):
        chunk = [{"query": ip} for _, ip, _ in ok[i:i+100]]
        try:
            d = json.loads(get('http://ip-api.com/batch', data=json.dumps(chunk).encode(),
                               headers={'Content-Type': 'application/json'}, timeout=30))
            for x in d:
                if x.get('status') == 'success':
                    out[x['query']] = (x.get('countryCode', ''), x.get('city', ''))
        except Exception as e:
            print('geo err', e)
        time.sleep(1)
    return out

geos = geo(ok)
names = {'HK': '香港', 'JP': '日本', 'SG': '新加坡', 'KR': '韩国', 'TW': '台北', 'CN': '中国',
         'AU': '澳洲', 'PH': '菲律宾', 'ID': '印尼', 'NZ': '新西兰', 'TH': '泰国', 'MY': '马来',
         'VN': '越南', 'US': '美国', 'GB': '英国', 'DE': '德国', 'NL': '荷兰', 'FR': '法国', 'CA': '加拿大'}
asian = {'HK', 'JP', 'SG', 'KR', 'TW', 'CN', 'TH', 'MY', 'VN', 'PH', 'ID', 'NZ', 'AU'}
ports = ['8443', '2053', '2083', '2087', '2096']
rows = []
for i, (pfx, ip, colo) in enumerate(sorted(ok, key=lambda x: (names.get(geos.get(x[1], ('ZZ',))[0], 'zz')))):
    cc, city = geos.get(ip, ('', ''))
    star = '★' if cc in asian else ''
    tag = names.get(cc, cc or '?')
    rows.append((cc, pfx, ip, colo, f"{ip}:{ports[i % 5]}{star}#借壳{tag}-{city[:10]}[{colo}]"))

with open('byoip_latest.txt', 'w') as f:
    f.write(f"# 自动生成 {time.strftime('%F %T UTC', time.gmtime())} by byoip_refresh.py | 总数{len(rows)} | ★=亚洲属地优先 | #尾段=CF落点colo\n")
    for cc, pfx, ip, colo, line in rows:
        f.write(line + '\n')
with open('byoip_ips.txt', 'w') as f:
    f.write('\n'.join(ip for _, _, ip, _, _ in rows) + '\n')
print(f'写出 byoip_latest.txt ({len(rows)}条)，亚洲优先前5:')
for cc, pfx, ip, colo, line in rows[:5]:
    print(' ', line)
