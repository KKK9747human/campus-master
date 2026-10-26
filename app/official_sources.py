"""官方通知源抓取：把「手动贴入」降为兜底，通知的第一信源改成学校官方栏目页。

设计取舍：
- 不上爬虫框架、不引 BeautifulSoup：三五个栏目页用正则解析足够，依赖越少越好维护；
- 解析规则是通用的（内容链接形如 /page.htm、/view/aid/…，标题取 title 属性或锚文本，
  日期取锚点邻近的日期，或 URL 里的 /2026/1023/ 段），换学校加源只改 notice_sources 一行数据；
- 只抓列表页第一页，尊重对方服务器：带浏览器 UA、15 秒超时，失败如实上报，绝不静默塞脏数据。
"""
import re
from urllib.parse import urljoin

import httpx

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 内容页特征：导航/栏目/登录这类链接长这样的一律不要
_CONTENT_PAT = re.compile(r"(/page\.htm|/view/aid/|/art/\d|/info/|/20\d{2}/\d{3,4}[a-z]?\d+)", re.I)
_DATE_PAT = re.compile(r"20\d{2}\s*[-/.年]\s*\d{1,2}\s*[-/.月]\s*\d{1,2}")
_URL_DATE_PAT = re.compile(r"/(20\d{2})[/.](\d{2})(\d{2})/")
_TAG_PAT = re.compile(r"<[^>]+>")
_NAV_TITLE = ("首页", "登录", "注册", "联系我们", "网站地图", "返回", "English",
              "校长信箱", "更多", "旧版", "无障碍", "统一身份认证", "部门导航")


def _attr(tag: str, name: str) -> str:
    m = re.search(rf"{name}\s*=\s*[\"']([^\"']*)[\"']", tag, re.I)
    return (m.group(1) if m else "").strip()


def _text_after(html: str, pos: int, span: int = 300) -> str:
    seg = html[pos:pos + span]
    if "</a>" in seg:
        seg = seg.split("</a>")[0]
    return re.sub(r"\s+", " ", _TAG_PAT.sub(" ", seg)).strip()


def _to_date(text: str):
    m = re.search(r"(20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})", text)
    if not m:
        return None
    try:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    except ValueError:
        return None


def _date_near(html: str, pos: int):
    m = _DATE_PAT.search(html[pos:pos + 260])
    if m:
        return _to_date(m.group(0))
    m = _DATE_PAT.search(html[max(0, pos - 160):pos])
    return _to_date(m.group(0)) if m else None


def parse_list(html: str, base_url: str, cap: int = 30) -> list:
    """通用列表解析：内容链接 + 标题 + 尽力而为的日期。宁缺毋滥，解析不出就返回空列表"""
    items, seen = [], set()
    for m in re.finditer(r"<a\b[^>]*>", html, re.I):
        tag = m.group(0)
        href = _attr(tag, "href")
        if not href or href.startswith(("javascript", "#", "mailto")):
            continue
        url = urljoin(base_url, href)
        if not _CONTENT_PAT.search(url):
            continue
        title = (_attr(tag, "title") or _text_after(html, m.end())).strip()
        if len(title) < 8 or any(w in title for w in _NAV_TITLE):
            continue
        if url in seen:
            continue
        seen.add(url)
        d = _date_near(html, m.end())
        if not d:
            mu = _URL_DATE_PAT.search(url)
            if mu:
                try:
                    d = f"{mu.group(1)}-{int(mu.group(2)):02d}-{int(mu.group(3)):02d}"
                except ValueError:
                    d = None
        items.append({"title": title[:190], "url": url, "publish_date": d})
        if len(items) >= cap:
            break
    return items


def _decode(resp: httpx.Response) -> str:
    raw = resp.content
    for enc in (resp.charset_encoding, "utf-8", "gb18030"):
        if not enc:
            continue
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", errors="ignore")


def fetch_page(url: str) -> str:
    with httpx.Client(verify=False, timeout=15, follow_redirects=True,
                      headers={"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}) as cli:
        r = cli.get(url)
        r.raise_for_status()
        return _decode(r)


def extract_detail_text(html: str, cap: int = 900, drop: str = "") -> str:
    """详情页正文：去 script/style 后按行收「像正文的长句」。
    页脚/横幅噪音（版权、备案、校园胜景轮播图 alt、标题回显）一律不进正文"""
    h = re.sub(r"<(script|style|head)\b[\s\S]*?</\1>", " ", html, flags=re.I)
    drop = (drop or "").strip()
    out = []
    for l in (s.strip() for s in _TAG_PAT.sub("\n", h).splitlines()):
        if len(l) < 18:
            continue
        if l.startswith(("Copyright", "版权所有", "地址：", "邮编", "浙ICP")) \
                or any(k in l for k in ("公网安备", "ICP备", "网站标识码")):
            continue
        if len(l) <= 24 and ("胜景" in l or "校园风光" in l):
            continue
        if drop and (l == drop or l.startswith(drop)):
            continue
        out.append(l)
    return "\n".join(out)[:cap]
