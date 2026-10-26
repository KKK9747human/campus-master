"""
=====================================================================
 掌控校园 (Campus Master) —— 后端服务入口（第一步：项目骨架）
=====================================================================
 本文件职责：
   1. 启动 FastAPI Web 服务
   2. 连接华为云 RDS for MySQL   （存核心业务数据：通知/帖子/知识图谱）
   3. 连接华为云 Redis (DCS 实例) （存热点数据：首页最新通知缓存等）
   4. 提供 /health 健康检查接口，一键排查云服务连通性问题

 启动命令（在 campus-master 目录下执行）：
   uvicorn app.main:app --reload --port 8000

 启动成功后浏览器访问：
   http://127.0.0.1:8000/docs   ← FastAPI 自动生成的接口测试页（强烈推荐玩一下）
=====================================================================
"""

# ---------------------------------------------------------------------
# 一、导入需要用到的包
# ---------------------------------------------------------------------
import os        # Python 内置：读取环境变量（数据库密码等敏感信息不写死在代码里）
import json      # Python 内置：JSON 与 Python 对象互转（与前端/Redis 交换数据的格式）
import time      # Python 内置：perf_counter 计时，给缓存命中/回源打耗时标签
import threading # Python 内置：后台守护线程跑官方源定时抓取
import uuid      # Python 内置：生成上传图片的随机文件名
from collections import Counter   # Python 内置：技能提炼时按标签/场景聚合计数
from datetime import date, datetime   # Python 内置：上传文件名带日期 / 简报按天数打新近分

from dotenv import load_dotenv    # 第三方：把 .env 文件里的配置加载进环境变量
import pymysql                   # 第三方：Python 连接 MySQL 的驱动 → 连华为云 RDS 用它
import redis                     # 第三方：Python 的 Redis 客户端    → 连华为云 DCS 用它
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel   # 第三方：请求体校验（FastAPI 自带依赖）

from app import ai               # 本项目 AI 能力层：大模型调用 + 本地规则降级
from app import handbook         # 安全雷达的证据层：实体富化 + 条款检索 + 置信度
from app import official_sources as osrc   # 官方通知源抓取：列表页解析 + 详情页正文

# ---------------------------------------------------------------------
# 二、读取配置（全部从 .env 文件读取，模拟 IP/密码只存在于 .env 中）
# ---------------------------------------------------------------------
load_dotenv()   # 执行后，.env 里的每一行 KEY=VALUE 就能被 os.getenv() 读到

# ---- 华为云 RDS for MySQL 连接信息（当前为模拟值，请替换成你控制台里看到的）----
MYSQL_HOST     = os.getenv("MYSQL_HOST", "127.0.0.1")           # RDS 实例连接地址
MYSQL_PORT     = int(os.getenv("MYSQL_PORT", "3306"))           # RDS 端口，默认 3306
MYSQL_USER     = os.getenv("MYSQL_USER", "root")                # 数据库账号
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")                # 数据库密码
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "campus_master")   # 连接哪个库

# ---- 华为云 Redis (DCS) 连接信息（当前为模拟值，请替换成你实例详情页的地址）----
REDIS_HOST     = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT     = int(os.getenv("REDIS_PORT", "6379"))           # Redis 端口，默认 6379
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")

# 官方源定时抓取间隔（分钟）；0 或负数 = 关闭定时任务，只保留手动「拉取最新」按钮
FETCH_INTERVAL_MINUTES = int(os.getenv("FETCH_INTERVAL_MINUTES", "30"))

# ---------------------------------------------------------------------
# 三、创建 FastAPI 应用实例（整个后端只有这一个 app）
# ---------------------------------------------------------------------
app = FastAPI(
    title="掌控校园 API",
    description="赛题1：基于华为云 RDS + Redis + AI 大模型的校园信息一体化平台",
    version="0.1.0",
)

# CORS：允许 web/ 下的页面（哪怕双击 file:// 打开）跨域调用本接口
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态前端：web/ 目录下的页面可直接通过 http://127.0.0.1:8000/web/xxx.html 访问
_WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
if os.path.isdir(_WEB_DIR):
    app.mount("/web", StaticFiles(directory=_WEB_DIR, html=True), name="web")

# 论坛配图：POST /upload 落盘到这里，GET /uploads/文件名 直接访问
_UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")
os.makedirs(_UPLOAD_DIR, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_UPLOAD_DIR), name="uploads")

# ---------------------------------------------------------------------
# 四、数据库连接工具
# ---------------------------------------------------------------------
def get_mysql_conn():
    """
    每次调用都新建一个 MySQL 连接，用完必须 close()。
    （写法简单直观，适合起步；以后访问量大了再换成连接池）
    """
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        charset="utf8mb4",                       # 支持中文，必须加
        cursorclass=pymysql.cursors.DictCursor,  # 查询结果返回字典而非元组，按字段名取值更直观
        connect_timeout=5,                       # 5 秒连不上就报错，避免页面一直卡死
    )


# Redis 客户端：全局只创建一个（redis-py 内部自带连接池，可放心复用）
# 注意：redis.Redis(...) 这一行并不会立刻发起连接，执行第一条命令时才真正连
redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    password=REDIS_PASSWORD or None,
    decode_responses=True,       # 让 get 出来的是字符串，而不是 b'xxx' 字节串
    socket_connect_timeout=3,
    protocol=2,                  # 强制 RESP2 握手：兼容 Windows 版老 Redis（不发的 HELLO 命令）
)


# 缓存命中可视化：响应里带上 cache={hit, key, ms}，前端据此显示
# 「Redis 命中 · 0.4ms」或「MySQL 回源 · 3.2ms」，评委肉眼可验缓存策略真的生效
def cache_flag(key: str, hit: bool, t0: float) -> dict:
    return {"hit": hit, "key": key, "ms": round((time.perf_counter() - t0) * 1000, 1)}

# ---------------------------------------------------------------------
# 五、接口定义（前端访问的每个网址 = 一个接口）
# ---------------------------------------------------------------------
@app.get("/")
def index():
    """根路径：评委第一眼看到的落地页（web/index.html），文件不存在时退回 JSON 欢迎信息"""
    page = os.path.join(_WEB_DIR, "index.html")
    if os.path.isfile(page):
        return FileResponse(page)
    return {
        "project": "掌控校园 Campus Master",
        "docs": "/docs",
        "pages": ["/web/notice.html", "/web/kg_demo.html", "/web/forum.html",
                  "/web/safety.html", "/web/profile.html"],
    }


@app.get("/health")
def health_check():
    """
    健康检查：分别 ping 一下 MySQL 和 Redis，返回各自状态。
    新手排错神器：哪一个报错，就说明哪一个云服务没配置好。
    """
    result = {"status": "ok", "mysql": "-", "redis": "-"}

    # ---- 测试 MySQL：执行一句最简单的 SELECT 1 ----
    try:
        conn = get_mysql_conn()
        try:
            with conn.cursor() as cursor:
                cursor.execute("SELECT 1")
            result["mysql"] = "connected"
        finally:
            conn.close()               # 无论成功失败，连接都要关掉
    except Exception as e:
        result["mysql"] = f"failed: {e}"
        result["status"] = "error"

    # ---- 测试 Redis：能 ping 通即认为可用 ----
    try:
        redis_client.ping()
        result["redis"] = "connected"
    except Exception as e:
        result["redis"] = f"failed: {e}"
        result["status"] = "error"

    return result


@app.get("/notices/latest")
def get_latest_notices():
    """
    查询最新 5 条通知 —— 完整演示赛题要求的 Redis 缓存策略：
      第 1 步：先查 Redis 缓存（key: home:latest_notices，10 分钟过期）
      第 2 步：缓存里没有 → 去查 MySQL
      第 3 步：把 MySQL 结果写回 Redis，下一个用户就能"秒开"
    """
    cache_key = "home:latest_notices"    # 约定好的缓存键名（对应赛题缓存设计）
    t0 = time.perf_counter()

    # ---- 第 1 步：先问 Redis 要 ----
    cached = redis_client.get(cache_key)
    if cached:
        # 命中缓存：直接返回（from_cache=True 让你肉眼确认缓存真的生效了）
        return {"from_cache": True, "cache": cache_flag(cache_key, True, t0), "data": json.loads(cached)}

    # ---- 第 2 步：缓存没有，去 MySQL 查最新 5 条 ----
    conn = get_mysql_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT id, title, summary, ai_source, source_url, publish_date
                FROM notices
                ORDER BY created_at DESC
                LIMIT 5
                """
            )
            rows = cursor.fetchall()
    finally:
        conn.close()

    # ---- 第 3 步：结果转成 JSON 字符串写入 Redis，ex=600 表示 600 秒后自动过期 ----
    redis_client.set(cache_key, json.dumps(rows, default=str), ex=600)

    return {"from_cache": False, "cache": cache_flag(cache_key, False, t0), "data": rows}


@app.post("/debug/drop-cache")
def drop_cache():
    """演示辅助：手动清掉所有缓存，让评委亲眼看到 miss→查库→回填 全过程"""
    redis_client.delete("home:latest_notices", "handbook:clauses")
    for role in ROLE_ANCHORS:
        redis_client.delete(f"path:{role}")
    for pat in ("profile:*", "plan:*", "briefing:*"):   # 昵称是动态的，按前缀扫
        for k in list(redis_client.scan_iter(match=pat, count=100)):
            redis_client.delete(k)
    return {"ok": True}


# =====================================================================
# 模块1：AI 校园情报官 —— 通知文本 → 大模型抽取 → 入库 + 缓存失效
# =====================================================================
class NoticeIn(BaseModel):
    title: str
    content: str
    source_url: str = ""
    publish_date: str = ""     # 形如 2026-10-25，可留空


@app.post("/notices/ai")
def ai_ingest_notice(n: NoticeIn):
    """
    赛题模块1 主流程：
      用户贴通知原文 → 大模型提取 摘要/来源/时间/事件（严格 JSON）
      → 写入 MySQL notices 表 → 删掉 Redis 首页缓存（下次查询自动重建）
    """
    result = ai.extract_notice(n.title, n.content)

    conn = get_mysql_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO notices (title, content, summary, ai_source, source_url, publish_date)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    n.title,
                    n.content,
                    result["summary"],
                    result["source"],
                    n.source_url or None,
                    n.publish_date or None,
                ),
            )
            new_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()

    redis_client.delete("home:latest_notices")   # 数据变了，旧缓存立即作废

    return {"id": new_id, "ai": result,
            "note": "缓存已失效，下次 GET /notices/latest 会重新查库并回填缓存"}


# ---------------------------------------------------------------------
# 模块1 延伸：官方通知源聚合（主链路）——手动贴入降级为兜底
#   notice_sources 表里每行一个官方源（如杭电教务处列表页）；
#   抓取入库只存标题+链接（content 空、summary 空），点「AI 一句话」才抓详情页补摘要；
#   官方与手动用 source_url 区分：抓取来的以 http 开头，手动贴入的多半为空。
# ---------------------------------------------------------------------
@app.get("/notices/sources")
def list_notice_sources(school: str = ""):
    """官方通知源清单（notice_sources 表）；school 为空返回全部"""
    sql = ("SELECT id, school, dept, url, note, last_fetch_at, last_new "
           "FROM notice_sources")
    params = []
    if school.strip():
        sql += " WHERE school=%s AND enabled=1"
        params.append(school.strip())
    sql += " ORDER BY id"
    conn = get_mysql_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
    finally:
        conn.close()
    return {"data": rows}


def run_official_fetch(school: str, per_source: int = 12) -> dict:
    """
    官方源抓取核心逻辑——手动「拉取最新」按钮与后台定时任务共用这一份：
      读启用的源 → 逐个抓列表页 → 解析通知条目 → 按 source_url 去重入库
    每个源独立 try/except：一个源挂了不影响别的源，失败原因原样报给前端。
    """
    school = school.strip()
    if not school:
        raise HTTPException(status_code=400, detail="必须指定学校，例：?school=杭州电子科技大学")

    conn = get_mysql_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, dept, url FROM notice_sources WHERE school=%s AND enabled=1",
                (school,),
            )
            sources = cursor.fetchall()
    finally:
        conn.close()
    if not sources:
        raise HTTPException(status_code=404, detail=f"「{school}」还没有录入官方通知源")

    report, total_new = [], 0
    for src in sources:
        item = {"dept": src["dept"], "url": src["url"], "fetched": 0, "new": 0, "error": ""}
        try:
            html = osrc.fetch_page(src["url"])
            items = osrc.parse_list(html, src["url"], cap=max(per_source, 1))
        except Exception as e:
            item["error"] = f"抓取失败：{e}"
            report.append(item)
            continue
        item["fetched"] = len(items)
        conn = get_mysql_conn()
        try:
            with conn.cursor() as cursor:
                for it in items:
                    cursor.execute("SELECT id FROM notices WHERE source_url=%s", (it["url"],))
                    if cursor.fetchone():
                        continue
                    cursor.execute(
                        """INSERT INTO notices (title, content, summary, ai_source,
                                                 source_url, publish_date)
                           VALUES (%s, '', NULL, %s, %s, %s)""",
                        (it["title"], src["dept"], it["url"], it["publish_date"]),
                    )
                    item["new"] += 1
                cursor.execute(
                    "UPDATE notice_sources SET last_fetch_at=NOW(), last_new=%s WHERE id=%s",
                    (item["new"], src["id"]),
                )
            conn.commit()
        finally:
            conn.close()
        total_new += item["new"]
        report.append(item)

    if total_new:
        redis_client.delete("home:latest_notices")
    return {"school": school, "total_new": total_new, "report": report,
            "note": "新通知只入了标题与链接；点「AI 一句话」才会抓详情页生成摘要"}


@app.post("/notices/fetch")
def fetch_official_notices(school: str, per_source: int = 12):
    """手动触发官方源抓取（与后台定时任务走同一套 run_official_fetch）"""
    return run_official_fetch(school, per_source)


# ---------------------------------------------------------------------
# 官方源定时抓取：后台守护线程，每 FETCH_INTERVAL_MINUTES 分钟自动跑一轮
#   （.env 配 FETCH_INTERVAL_MINUTES 可调，0=关闭；零新依赖，不引 APScheduler）
# ---------------------------------------------------------------------
def _fetch_cron_round() -> None:
    """对库里所有启用了官方源的学校各抓一轮，结果打进 uvicorn 日志"""
    conn = get_mysql_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT DISTINCT school FROM notice_sources WHERE enabled=1")
            schools = [r["school"] for r in cursor.fetchall()]
    finally:
        conn.close()
    for school in schools:
        try:
            report = run_official_fetch(school)
            print(f"[fetch-cron] {school}：本轮新增 {report['total_new']} 条官方通知", flush=True)
        except Exception as e:   # 单校失败不能杀死调度线程
            print(f"[fetch-cron] {school} 抓取失败：{e}", flush=True)


def _fetch_cron_loop() -> None:
    time.sleep(60)              # 冷启动先让路（连库/首屏优先），1 分钟后跑首轮
    while True:
        _fetch_cron_round()
        time.sleep(FETCH_INTERVAL_MINUTES * 60)


if FETCH_INTERVAL_MINUTES > 0:
    threading.Thread(target=_fetch_cron_loop, daemon=True, name="official-fetch-cron").start()
    print(f"[fetch-cron] 官方源定时抓取已启用：每 {FETCH_INTERVAL_MINUTES} 分钟一轮"
          f"（.env FETCH_INTERVAL_MINUTES 可调，0=关闭）", flush=True)


@app.get("/notices/official")
def list_official_notices(school: str = "", dept: str = "", limit: int = 30):
    """官方源入库的通知（source_url 以 http 开头），按发布日期倒序"""
    where, params = ["source_url LIKE %s"], ["http%"]
    if dept.strip():
        where.append("ai_source=%s")
        params.append(dept.strip())
    if school.strip():
        where.append("ai_source IN (SELECT dept FROM notice_sources WHERE school=%s)")
        params.append(school.strip())
    sql = ("SELECT id, title, ai_source, source_url, publish_date, summary, created_at "
           "FROM notices WHERE " + " AND ".join(where) +
           " ORDER BY COALESCE(publish_date, DATE(created_at)) DESC, id DESC LIMIT %s")
    params.append(min(limit, 50))
    conn = get_mysql_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
    finally:
        conn.close()
    return {"data": rows}


# ---------------------------------------------------------------------
# 模块1 延伸：情报官个性化简报 —— 相关度打分/筛选全部由代码算（可回溯），
#   大模型只负责把入选通知整合成一段导语（同雷达纪律：不许编造没喂给它的内容）。
#   通知标题里出现的图谱概念会带出「去知识网格看」的入口，把两条线缝起来。
# ---------------------------------------------------------------------
ROLE_KEYWORDS = {
    "freshman":  ["新生", "入学", "军训", "选课", "四六级", "英语", "社团", "竞赛", "基础", "讲座"],
    "contest":   ["竞赛", "蓝桥杯", "比赛", "报名", "ACM", "集训", "程序设计", "算法", "选拔"],
    "jobseeker": ["招聘", "实习", "宣讲", "双选", "校招", "求职", "就业", "简历", "岗位"],
    "postgrad":  ["考研", "初试", "复试", "调剂", "硕士", "推免", "研究生", "夏令营"],
}


@app.get("/notices/briefing")
def notice_briefing(nickname: str = ""):
    """个性化简报：档案 → 相关度打分 → Top6 → AI 整合导语 + 通知↔图谱概念关联"""
    t0 = time.perf_counter()
    profile = _read_profile(nickname.strip()) if nickname.strip() else None
    cache_key = f"briefing:{nickname.strip() or '_'}"
    cached = redis_client.get(cache_key)
    if cached:
        return {"from_cache": True, "cache": cache_flag(cache_key, True, t0), "data": json.loads(cached)}

    conn = get_mysql_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, title, ai_source, source_url, publish_date, summary, created_at "
                "FROM notices ORDER BY COALESCE(publish_date, DATE(created_at)) DESC, id DESC LIMIT %s",
                (40,))
            recent = cursor.fetchall()
            cursor.execute("SELECT name FROM kg_nodes")
            kg_names = [r["name"] for r in cursor.fetchall()]
            school_depts = set()
            if profile and profile.get("school"):
                cursor.execute("SELECT dept FROM notice_sources WHERE school=%s", (profile["school"],))
                school_depts = {r["dept"] for r in cursor.fetchall()}
    finally:
        conn.close()

    role = (profile or {}).get("role") or ""
    kws = ROLE_KEYWORDS.get(role, [])
    role_label = ROLE_ANCHORS[role]["label"] if role in ROLE_ANCHORS else "在校生"
    today = date.today()
    scored = []
    for row in recent:
        text = f"{row['title']} {row['summary'] or ''}"
        hits = sorted({k for k in kws if k in text})
        d = row["publish_date"] or (row["created_at"].date() if row["created_at"] else today)
        days = max(0, (today - d).days)
        score = len(hits) * 18
        score += 12 if (school_depts and row["ai_source"] in school_depts) else 0
        score += 14 if days <= 3 else 10 if days <= 7 else 6 if days <= 14 else 3 if days <= 30 else 0
        if score <= 0:
            continue
        concepts = [n for n in kg_names if n in row["title"]]   # 标题里出现的图谱概念才带出，宁缺毋滥
        scored.append({
            "id": row["id"], "title": row["title"], "dept": row["ai_source"],
            "date": str(d), "score": score, "why": hits,
            "official": bool((row["source_url"] or "").startswith("http")),
            "url": row["source_url"] or "",
            "kg": concepts,
        })
    scored.sort(key=lambda x: (-x["score"], -x["id"]))   # 相关度优先；同分时新的在前
    scored = scored[:6]

    if scored:
        notice_lines = [f"《{s['title']}》（{s['dept']}，{s['date']}）" for s in scored]
        prof_bits = []
        if profile:
            if profile.get("school"):
                prof_bits.append(f"学校 {profile['school']}")
            prof_bits.append(f"身份 {role_label}")
            if profile.get("goal"):
                prof_bits.append(f"目标 {profile['goal']}")
            if profile.get("major"):
                prof_bits.append(f"专业 {profile['major']}")
        profile_text = "，".join(prof_bits) or None
        lead = ai.brief_intro(profile_text, notice_lines)
    else:
        lead = {"intro": "近 40 条通知里没筛出和你档案强相关的——先去「拉取最新」抓一轮官方源，"
                         "或在个人中心补全身份，命中的关键词越多排得越准。", "engine": "local-rules"}

    data = {
        "intro": lead["intro"], "engine": lead["engine"],
        "items": scored,
        "profile": {"school": (profile or {}).get("school"), "role": role,
                    "role_label": role_label, "goal": (profile or {}).get("goal")},
        "scanned": len(recent),
    }
    redis_client.set(cache_key, json.dumps(data, default=str), ex=600)
    return {"from_cache": False, "cache": cache_flag(cache_key, False, t0), "data": data}


@app.post("/notices/{notice_id}/summarize")
def summarize_official_notice(notice_id: int):
    """AI 一句话摘要：按需抓详情页正文 → ai.summarize_official → 写回 notices.summary"""
    conn = get_mysql_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, title, source_url, summary FROM notices WHERE id=%s",
                (notice_id,),
            )
            row = cursor.fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="通知不存在")
    if not (row["source_url"] or "").startswith("http"):
        raise HTTPException(
            status_code=400,
            detail="手动贴入的通知没有详情页链接，摘要请走「AI 提炼」那条链路",
        )
    if row["summary"]:
        return {"id": notice_id, "summary": row["summary"], "from_cache": True}

    try:
        html = osrc.fetch_page(row["source_url"])
        text = osrc.extract_detail_text(html, drop=row["title"])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"详情页抓取失败：{e}")

    # 详情页抓不出正文（JS 渲染等）→ 摘要退化为标题，不假装成功
    if text:
        result = ai.summarize_official(row["title"], text)
    else:
        result = {"summary": row["title"][:42], "engine": "local-rules"}

    conn = get_mysql_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE notices SET summary=%s WHERE id=%s",
                           (result["summary"], notice_id))
        conn.commit()
    finally:
        conn.close()
    redis_client.delete("home:latest_notices")
    return {"id": notice_id, "summary": result["summary"],
            "engine": result["engine"], "from_cache": False}


@app.get("/notices/{notice_id}")
def get_notice(notice_id: int):
    """查看单条通知全文 + AI 摘要（溯源详情页用）"""
    conn = get_mysql_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM notices WHERE id=%s", (notice_id,))
            row = cursor.fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="通知不存在")
    return row


# =====================================================================
# 模块2：知识图谱 —— 经验帖入库、三元组抽取、图谱数据、路径推荐
# =====================================================================
class PostIn(BaseModel):
    title: str
    content: str
    author: str = "匿名"
    images: list[str] = []          # /upload 返回的站内 URL，最多 9 张


# 图片魔数 → 真实扩展名（不信客户端给的文件名后缀）
_IMG_MAGIC = ((b"\xff\xd8\xff", "jpg"), (b"\x89PNG", "png"), (b"GIF8", "gif"))


def _sniff_image_ext(data: bytes):
    for magic, ext in _IMG_MAGIC:
        if data.startswith(magic):
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


@app.post("/upload")
async def upload_image(file: UploadFile):
    """
    论坛配图上传：jpg/png/webp/gif 白名单 + 魔数校验 + 5MB 上限。
    文件名随机（日期+uuid），杜绝路径拼接和覆盖；返回站内 /uploads/ URL。
    """
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片不能超过 5MB")
    ext = _sniff_image_ext(data)
    if not ext:
        raise HTTPException(status_code=400, detail="只支持 jpg/png/webp/gif 真实图片")
    name = f"{datetime.now():%Y%m%d}_{uuid.uuid4().hex[:12]}.{ext}"
    with open(os.path.join(_UPLOAD_DIR, name), "wb") as f:
        f.write(data)
    return {"url": f"/uploads/{name}"}


RELATION_LABELS = {"prerequisite": "前置", "related": "相关", "contains": "包含"}

# 身份 → 图谱"目标锚点"：从锚点沿前置边反向回溯，即为该身份的推荐学习路径
ROLE_ANCHORS = {
    "freshman":   {"target": "数据结构", "label": "大一新生·打基础"},
    "contest":    {"target": "蓝桥杯",   "label": "竞赛选手·冲蓝桥杯"},
    "jobseeker":  {"target": "实习",     "label": "求职党·拿实习"},
    "postgrad":   {"target": "考研复试", "label": "考研党·进复试"},
}

# 精华帖判定：posts 表是赛题固定结构，不加字段，按点赞数打标签
ESSENCE_LIKES = 30


def _prereq_adj(links: list) -> dict:
    """target -> [前置节点名...]，只收「前置」边（图谱里唯一表示学习先后的关系）"""
    adj: dict = {}
    for lk in links:
        if lk["relation"] == "prerequisite":
            adj.setdefault(lk["target"], []).append(lk["source"])
    return adj


def _dependents_adj(links: list) -> dict:
    """source(前置) -> [后面要用它的节点...]，_prereq_adj 的反向，给拓扑排序和「为什么补这步」用"""
    dep: dict = {}
    for lk in links:
        if lk["relation"] == "prerequisite":
            dep.setdefault(lk["source"], []).append(lk["target"])
    return dep


def _hops_from(anchor: str, prereq_of: dict) -> dict:
    """从锚点沿前置边反向 BFS：hop = 该节点离目标几层，首次访问即最短（脏数据成环也收得住）"""
    hop = {anchor: 0}
    bfs = [anchor]
    while bfs:
        cur = bfs.pop(0)
        for pre in prereq_of.get(cur, []):
            if pre not in hop:
                hop[pre] = hop[cur] + 1
                bfs.append(pre)
    return hop


def _learn_layers(node_names: list, prereq_of: dict) -> dict:
    """全局学习阶段（分层视图的列号）：没有前置课的在第 0 列，其余 = 最长前置链深度 + 1。
    这样任意一条「前置」边一定从左列指向右列，图的排布就有规律可读。"""
    depth: dict = {}
    visiting: set = set()

    def of(name: str) -> int:
        if name in depth:
            return depth[name]
        if name in visiting:          # 成环时截断，避免无限递归
            return 0
        visiting.add(name)
        pres = [p for p in prereq_of.get(name, []) if p in name_set and p != name]
        val = 0 if not pres else 1 + max(of(p) for p in pres)
        visiting.discard(name)
        depth[name] = val
        return val

    name_set = set(node_names)
    return {n: of(n) for n in node_names}



@app.post("/posts")
def create_post(p: PostIn):
    """
    赛题模块2 主流程（一步到位）：
      发布经验帖 → 存 posts 表 → 大模型抽三元组 → 合并进 kg_nodes/kg_edges
      → 作废所有学习路径缓存（图谱变了）
    """
    conn = get_mysql_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT name FROM kg_nodes")
            known_names = [r["name"] for r in cursor.fetchall()]
    finally:
        conn.close()

    # 把已有节点名喂给抽取引擎，做残缺片段→完整节点归并（见 ai._resolve_alias）
    triples = ai.extract_triples(p.title, p.content, known_names)

    conn = get_mysql_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "INSERT INTO posts (title, content, author) VALUES (%s, %s, %s)",
                (p.title, p.content, p.author),
            )
            post_id = cursor.lastrowid

            # 配图：只收本站 /uploads/ 开头的 URL（防外链注入），最多 9 张
            for i, img in enumerate(p.images[:9]):
                if img.startswith("/uploads/"):
                    cursor.execute(
                        "INSERT INTO post_media (post_id, url, sort) VALUES (%s, %s, %s)",
                        (post_id, img, i))

            # 节点：同名已存在则只补描述，不存在则插入（uk_node_name 唯一键防重）
            node_id_by_name = {}
            for nd in triples.get("nodes", []):
                cursor.execute("SELECT id FROM kg_nodes WHERE name=%s", (nd["name"],))
                hit = cursor.fetchone()
                if hit:
                    node_id_by_name[nd["name"]] = hit["id"]
                else:
                    cursor.execute(
                        "INSERT INTO kg_nodes (name, type, description, source_post_id) VALUES (%s, %s, %s, %s)",
                        (nd["name"], nd.get("type", "skill"), nd.get("description", ""), post_id),
                    )
                    node_id_by_name[nd["name"]] = cursor.lastrowid

            for ed in triples.get("edges", []):
                s, t = node_id_by_name.get(ed["source"]), node_id_by_name.get(ed["target"])
                if s and t and s != t:
                    cursor.execute(
                        """INSERT IGNORE INTO kg_edges (source_node_id, target_node_id, relation)
                           VALUES (%s, %s, %s)""",
                        (s, t, ed.get("relation", "related")),
                    )
        conn.commit()
    finally:
        conn.close()

    for role in ROLE_ANCHORS:
        redis_client.delete(f"path:{role}")     # 图谱更新 → 缓存的学习路径全部作废

    return {"post_id": post_id, "triples": triples}


@app.get("/posts/latest")
def latest_posts(limit: int = 20, filter: str = "all", keyword: str = "", author: str = ""):
    """
    论坛列表：filter=all|essence|mine，可选关键词搜索。
    精华按点赞数阈值判定（ESSENCE_LIKES），不改 posts 表结构。
    """
    where, params = [], []
    if filter == "essence":
        where.append("likes >= %s")
        params.append(ESSENCE_LIKES)
    elif filter == "mine":
        if not author:
            raise HTTPException(status_code=400, detail="筛选「我的帖子」必须带 author 参数")
        where.append("author = %s")
        params.append(author)
    if keyword.strip():
        where.append("(title LIKE %s OR content LIKE %s)")
        params += [f"%{keyword.strip()}%"] * 2
    sql = ("SELECT id, title, content, author, likes, created_at FROM posts ")
    if where:
        sql += "WHERE " + " AND ".join(where) + " "
    sql += "ORDER BY " + ("likes DESC, created_at DESC " if filter == "essence"
                          else "created_at DESC ")
    sql += "LIMIT %s"
    params.append(min(limit, 50))

    conn = get_mysql_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
    finally:
        conn.close()
    if rows:
        ids = [r["id"] for r in rows]
        ph = ",".join(["%s"] * len(ids))
        conn = get_mysql_conn()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT post_id, url FROM post_media WHERE post_id IN ({ph}) "
                    "ORDER BY post_id, sort", ids)
                media = {}
                for m in cursor.fetchall():
                    media.setdefault(m["post_id"], []).append(m["url"])
        finally:
            conn.close()
        for r in rows:
            r["images"] = media.get(r["id"], [])
    for r in rows:
        r["is_essence"] = (r["likes"] or 0) >= ESSENCE_LIKES
    return {"data": rows, "essence_line": ESSENCE_LIKES}


@app.post("/posts/{post_id}/like")
def like_post(post_id: int):
    """点赞：论坛卡片按钮点一次 +1，够 30 赞自动进精华"""
    conn = get_mysql_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("UPDATE posts SET likes = likes + 1 WHERE id=%s", (post_id,))
            if cursor.rowcount == 0:
                raise HTTPException(status_code=404, detail="帖子不存在")
            cursor.execute("SELECT likes FROM posts WHERE id=%s", (post_id,))
            likes = cursor.fetchone()["likes"]
        conn.commit()
    finally:
        conn.close()
    return {"id": post_id, "likes": likes, "is_essence": likes >= ESSENCE_LIKES}


@app.get("/kg/graph")
def kg_graph(role: str = "", nickname: str = ""):
    """
    把 kg_nodes/kg_edges 转成 ECharts graph 直接可用的 nodes/links 结构。
    带 ?role= 时额外给出排布与筛选信息：
      layer   —— 全局学习阶段（分层视图的列号，0 = 无前置的入门课）
      on_path —— 是否在该身份目标锚点的前置子图里
      hop     —— 该身份视角下离目标还有几层（不在子图内为 null）
    带 ?nickname= 时每节点再标出它在不在该同学的学习清单里、学到哪一步
    """
    conn = get_mysql_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT id, name, type, description, source_post_id FROM kg_nodes")
            nodes = cursor.fetchall()
            cursor.execute(
                """
                SELECT e.source_node_id, e.target_node_id, e.relation,
                       s.name AS source_name, t.name AS target_name
                FROM kg_edges e
                JOIN kg_nodes s ON s.id = e.source_node_id
                JOIN kg_nodes t ON t.id = e.target_node_id
                """
            )
            edges = cursor.fetchall()
    finally:
        conn.close()

    links = [
        {
            "source": e["source_name"],
            "target": e["target_name"],
            "value": RELATION_LABELS.get(e["relation"], e["relation"]),
            "relation": e["relation"],
        }
        for e in edges
    ]
    prereq_of = _prereq_adj(links)
    layers = _learn_layers([nd["name"] for nd in nodes], prereq_of)

    hop = {}
    anchor = ROLE_ANCHORS.get(role, {}).get("target")
    if anchor and anchor in layers:
        hop = _hops_from(anchor, prereq_of)

    study = {r["node_name"]: r["status"] for r in _study_rows(nickname.strip())} if nickname.strip() else {}

    return {
        "role": role or None,
        "goal": anchor,
        "max_layer": max(layers.values()) if layers else 0,
        "nodes": [
            {
                "name": nd["name"],
                "id": nd["id"],
                "type": nd["type"],
                "description": nd["description"],
                "source_post_id": nd["source_post_id"],
                "layer": layers.get(nd["name"], 0),
                "on_path": nd["name"] in hop,
                "hop": hop.get(nd["name"]),
                "in_list": nd["name"] in study,
                "study_status": study.get(nd["name"]),
                "symbolSize": {"contest": 80, "course": 60, "skill": 70}.get(nd["type"], 60),
            }
            for nd in nodes
        ],
        "links": links,
    }


@app.get("/kg/path/{role}")
def recommend_path(role: str):
    """
    个性化学习路径（赛题 Redis 缓存策略 key: path:freshman）：
      先查 Redis → 未命中则在 MySQL 图谱上从目标锚点沿"前置"边反向回溯
      → 得到拓扑有序的学习路径 → 写回 Redis（30 分钟过期）
    """
    if role not in ROLE_ANCHORS:
        raise HTTPException(status_code=404,
                            detail=f"未知身份 {role}，可选: {', '.join(ROLE_ANCHORS)}")

    t0 = time.perf_counter()
    cached = redis_client.get(f"path:{role}")
    if cached:
        return {"from_cache": True, "cache": cache_flag(f"path:{role}", True, t0), "data": json.loads(cached)}

    graph = kg_graph()
    name_of = {n["name"]: n for n in graph["nodes"]}
    prereq_of = _prereq_adj(graph["links"])

    anchor = ROLE_ANCHORS[role]["target"]
    if anchor not in name_of:
        raise HTTPException(status_code=404,
                            detail=f"图谱中还没有「{anchor}」节点，请先发布相关经验帖")

    # 专属路径 = 到目标的最短前置链：从锚点沿「前置」边反向 BFS，hop 记每个节点离目标的层数
    # （图谱大了以后不再把所有可达课堆在一起，只推荐代价最小的一条主线，其余作可选支线）
    hop = _hops_from(anchor, prereq_of)
    seen = set(hop)                            # 锚点的全部前置子图，供前端高亮
    parent = {}
    for n in hop:
        best = None
        for pre in prereq_of.get(n, []):
            # 挑离目标最近（hop 最小）的前置作父，链才最短；hop 大 = 离目标远
            if pre in hop and (best is None or hop[pre] < hop[best]):
                best = pre
        if best:
            parent[n] = best
    chain, cur, guard = [], anchor, set()
    while cur and cur not in guard:            # guard：防脏数据成环导致死循环
        chain.append(cur)
        guard.add(cur)
        cur = parent.get(cur)
    steps = list(reversed(chain))              # 从最基础的一路学到目标
    extras = sorted(n for n in seen if n not in steps)   # 可达但不在主线上的选修

    path = [{
        "order": i + 1,
        "name": n,
        "type": name_of[n]["type"],
        "description": name_of[n]["description"],
    } for i, n in enumerate(steps)]

    data = {
        "role": role,
        "role_label": ROLE_ANCHORS[role]["label"],
        "goal": anchor,
        "path": path,
        "extras": [{"name": n, "type": name_of[n]["type"]} for n in extras],
        "graph_nodes": [name_of[n] for n in sorted(seen, key=lambda x: -hop.get(x, 99))],
        "graph_links": [
            lk for lk in graph["links"]
            if lk["relation"] == "prerequisite"
            and lk["source"] in seen and lk["target"] in seen
        ],
    }
    redis_client.set(f"path:{role}", json.dumps(data, default=str), ex=1800)
    return {"from_cache": False, "cache": cache_flag(f"path:{role}", False, t0), "data": data}


# =====================================================================
# 模块3：安全雷达 —— 求职鉴坑 + 聊天鉴诈 + 风险台账（risk_logs）
# =====================================================================
class ScanIn(BaseModel):
    text: str
    scene: str = "auto"        # auto=由文本判场景；也可显式传 job / fraud / notice
    skill: str = ""            # 可选检测技能（GET /safety/skills 的 id）：锁定依据池与场景
    nickname: str = ""


SCENE_KEYS = set(ai.SCENE_LABELS)

CLAUSE_FIELDS = ("id", "doc_title", "doc_year", "article_no", "title", "text",
                 "scene", "risk_type", "keywords", "source", "url", "trust", "note")


def _load_clauses():
    """条款库缓存（Redis handbook:clauses，10 分钟）：雷达每次扫描都要拿全量做匹配"""
    cached = None
    try:
        cached = redis_client.get("handbook:clauses")
    except redis.exceptions.RedisError:
        cached = None
    if cached:
        return json.loads(cached)
    conn = get_mysql_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"SELECT {', '.join(CLAUSE_FIELDS)} FROM handbook_articles "
                "WHERE verified = 1 AND enabled = 1 ORDER BY id")
            rows = cursor.fetchall()
    finally:
        conn.close()
    clauses = []
    for r in rows:
        row = {}
        for k, v in r.items():
            if k in ("id", "trust", "doc_year"):
                row[k] = None if v is None else int(v)
            else:
                row[k] = str(v or "")
        clauses.append(row)
    try:
        redis_client.set("handbook:clauses", json.dumps(clauses, default=str), ex=600)
    except redis.exceptions.RedisError:
        pass
    return clauses


def _tags_of(c: dict) -> list:
    return [t.strip() for t in (c.get("risk_type") or "").split(",") if t.strip()]


def _skill_pool(clauses: list, tag: str, scene: str) -> list:
    """技能池 = 带该标签的条款 + 同场景/通用的基础条款（risk_type 为空的背景法条）"""
    return [c for c in clauses
            if tag in _tags_of(c)
            or (not _tags_of(c) and c["scene"] in (scene, "all"))]


def _derive_skills(clauses: list) -> list:
    """技能不是写死的清单：从条款库 risk_type 标签聚类提炼，一个标签就是一项可选技能，
    每项自带依据池大小与出处文件——条款库增删后技能列表自动跟着变，依据永远有出处。"""
    buckets = {}
    for c in clauses:
        for tag in _tags_of(c):
            b = buckets.setdefault(tag, {"clauses": [], "kw": Counter(), "trust": [], "scenes": Counter()})
            b["clauses"].append(c)
            b["kw"].update(k.strip() for k in c["keywords"].split(",") if k.strip())
            b["trust"].append(int(c["trust"]))
            if c["scene"] != "all":
                b["scenes"][c["scene"]] += 1
    skills = []
    for tag, b in buckets.items():
        scene = b["scenes"].most_common(1)[0][0] if b["scenes"] else "fraud"
        docs = list(dict.fromkeys(f"{c['doc_title']}{c['article_no']}" for c in b["clauses"]))
        skills.append({
            "id": f"{scene}:{tag}", "name": tag, "scene": scene,
            "scene_label": ai.SCENE_LABELS.get(scene, scene),
            "pool": len(_skill_pool(clauses, tag, scene)), "core": len(b["clauses"]),
            "avg_trust": round(sum(b["trust"]) / len(b["trust"])),
            "docs": docs[:4],
            "sources": [{"label": handbook.SOURCE_LABEL.get(s, s), "n": n}
                        for s, n in Counter(c["source"] for c in b["clauses"]).most_common()],
            "keywords": [k for k, _ in b["kw"].most_common(8)],
        })
    skills.sort(key=lambda x: (-x["core"], x["scene"], x["name"]))
    return skills


@app.get("/safety/skills")
def safety_skills():
    """雷达技能列表：从条款库提炼的可选「检测技能」。
    选了技能再扫描，第三跳条款检索被限定在该技能的依据池里——引用必有出处。"""
    clauses = _load_clauses()
    return {"engine": "keyword-derive", "total_clauses": len(clauses),
            "data": _derive_skills(clauses)}


@app.post("/safety/scan")
def safety_scan(s: ScanIn):
    """
    统一风控入口，四跳链路一次跑完：
      hop1 实体富化（抠事实）→ hop2 风险判定（大模型 / 本地规则）
      → hop3 条款检索（只查 verified+enabled 的条款库，查不到就如实说没查到）
      → hop4 链路解释（大模型只把「条款为什么适用」说成人话，编号由代码给定）
    判级和依据全由代码算出来，大模型改不了；结果连同引用条款写进 risk_logs 形成台账。
    """
    text = s.text.strip()
    if len(text) < 10:
        raise HTTPException(status_code=400, detail="内容太短，至少 10 个字")

    facts = handbook.enrich(text)                                  # hop1
    lib = _load_clauses()                                          # hop3 的检索池
    scan_scene, skill_info = s.scene, None
    if s.skill:
        sk = next((k for k in _derive_skills(lib) if k["id"] == s.skill), None)
        if sk is None:
            raise HTTPException(status_code=400, detail="技能不存在或条款库刚更新，刷新技能列表再扫")
        scan_scene = sk["scene"]     # 选技能即锁定场景：技能本身就是一种带依据的场景视角
        lib = _skill_pool(lib, sk["name"], sk["scene"])
        skill_info = {"id": sk["id"], "name": sk["name"], "scene_label": sk["scene_label"],
                      "pool": len(lib), "docs": sk["docs"]}
    d = ai.scan(text, scan_scene)                                  # hop2
    for i, r in enumerate(d.get("risks", []), 1):
        r["no"] = i                                                # 证据编号，前端和链路都按它对齐

    cited, missing = handbook.cover(d["scene"], d.get("risks", []), text, lib)
    conf = handbook.confidence(cited)

    if d.get("risks"):                                             # hop4
        verdict, links, chain_advice, chain_engine = ai.chain_explain(
            d["scene_label"], d["level"], int(d.get("score") or 0),
            facts, d["risks"], cited, text)
    else:
        # 没抠出特征时不去烦大模型：这种结论最怕被读成「绝对安全」，话由代码写死
        verdict = ("暂未见风险：这段内容里没抠出可指认的可疑特征。"
                   "注意这不等于安全，换个说法可能就不同。")
        links, chain_advice, chain_engine = {}, "", "local-rules"

    degraded = [name for name, eng in
                (("风险判定", d.get("engine", "local-rules")), ("链路解释", chain_engine))
                if eng != "llm"]

    if cited:
        hop3 = f"命中 {len(cited)} 条可引用条款" + (
            f" · 技能「{skill_info['name']}」限定依据池 {skill_info['pool']} 条" if skill_info else "")
    elif d.get("risks"):
        hop3 = "条款库里没有对得上的条款，本条结论不给依据"
    else:
        hop3 = "没抠出风险项，本轮不需要引用条款"

    d.update({
        "verdict": verdict,
        "facts": facts,
        "skill": skill_info,
        "clauses": cited,
        "missing_basis": missing,
        "confidence": conf,
        "coverage": {"with_basis": sum(1 for r in d.get("risks", []) if r.get("basis")),
                     "total": len(d.get("risks", [])),
                     "cited_articles": len(cited)},
        "chain": [
            {"hop": 1, "name": "实体富化", "engine": "local-rules",
             "summary": f"抠出 {len(facts)} 类事实" if facts else "没抠出收费/证件/链接这类事实",
             "items": [f"{f['kind']}：{'、'.join(f['hits'])}" for f in facts]},
            {"hop": 2, "name": "风险判定", "engine": d.get("engine", "local-rules"),
             "summary": f"{ai.LEVEL_LABEL.get(d['level'], d['level'])} · 欺诈可能性 {d.get('score')} 分",
             "items": [f"E{r['no']} {r.get('type', '')}「{(r.get('quote') or '')[:24]}」"
                       for r in d.get("risks", [])]},
            {"hop": 3, "name": "条款检索", "engine": "keyword-match",
             "summary": hop3,
             "items": [f"C{c['no']} {c['doc_title']} {c['article_no']}"
                       f"（命中词：{'、'.join(c['matched']) or '无，按风险类型对齐'}）"
                       for c in cited] +
                       [f"未覆盖：{m['type']}" for m in missing]},
            {"hop": 4, "name": "链路解释", "engine": chain_engine,
             "summary": verdict,
             "items": [f"E{i} → {links[i]}" for i in sorted(links)]},
        ],
        "chain_advice": chain_advice,
        "degraded_to": degraded,
    })

    basis = "、".join(f"{c['doc_title']}{c['article_no']}" for c in cited)
    types = "、".join(r.get("type", "") for r in d.get("risks", []) if r.get("type"))

    conn = get_mysql_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO risk_logs (scene, nickname, excerpt, level, score, risk_types,
                                       engine, skill, cited_articles)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (d["scene"], s.nickname or "匿名", text[:180], d["level"],
                 int(d.get("score") or 0), types[:280], d.get("engine", "local-rules"),
                 skill_info["name"] if skill_info else None, basis[:280] or None),
            )
            log_id = cursor.lastrowid
        conn.commit()
    finally:
        conn.close()

    d["log_id"] = log_id
    return d


@app.get("/safety/handbook")
def safety_handbook(scene: str = "", source: str = "", q: str = "", limit: int = 60):
    """
    条款库本身也要能查：学生/评委可以直接翻雷达引用的每一条款从哪来。
    stats 里刻意分开「库里有几条」和「能引用几条」——核不到原文的一律锁着。
    """
    where, params = [], []
    if scene in SCENE_KEYS:
        where.append("scene = %s")
        params.append(scene)
    if source in handbook.SOURCE_LABEL:
        where.append("source = %s")
        params.append(source)
    if q:
        where.append("(doc_title LIKE %s OR article_no LIKE %s OR title LIKE %s "
                     "OR text LIKE %s OR keywords LIKE %s)")
        params += [f"%{q}%"] * 5
    sql = ("SELECT id, doc_title, doc_year, article_no, title, text, scene, risk_type, "
           "keywords, source, url, trust, verified, enabled, note "
           "FROM handbook_articles ")
    if where:
        sql += "WHERE " + " AND ".join(where) + " "
    sql += "ORDER BY doc_title, id LIMIT %s"
    params.append(min(max(limit, 1), 100))

    conn = get_mysql_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            cursor.execute(
                """
                SELECT scene, COUNT(*) AS c, SUM(enabled = 1) AS citable
                FROM handbook_articles GROUP BY scene
                """)
            by_scene = {r["scene"]: {"total": r["c"], "citable": int(r["citable"] or 0)}
                        for r in cursor.fetchall()}
            cursor.execute("SELECT source, COUNT(*) AS c FROM handbook_articles GROUP BY source")
            by_source = {r["source"]: r["c"] for r in cursor.fetchall()}
            cursor.execute(
                "SELECT doc_title, article_no, note FROM handbook_articles WHERE enabled = 0")
            locked = cursor.fetchall()
    finally:
        conn.close()
    for r in rows:
        r["source_label"] = handbook.SOURCE_LABEL.get(r["source"], r["source"])
    return {
        "data": rows,
        "stats": {"total": sum(v["total"] for v in by_scene.values()),
                  "citable": sum(v["citable"] for v in by_scene.values()),
                  "by_scene": by_scene, "by_source": by_source, "locked": locked},
    }


@app.get("/safety/logs")
def safety_logs(limit: int = 20, scene: str = "", nickname: str = ""):
    """风险台账：谁在什么时候扫过什么、判成什么等级、命中了哪些特征、引用了哪些条款"""
    where, params = [], []
    if scene in SCENE_KEYS:
        where.append("scene = %s")
        params.append(scene)
    if nickname:
        where.append("nickname = %s")
        params.append(nickname)
    sql = ("SELECT id, scene, nickname, excerpt, level, score, risk_types, engine, "
           "skill, cited_articles, created_at FROM risk_logs ")
    if where:
        sql += "WHERE " + " AND ".join(where) + " "
    sql += "ORDER BY created_at DESC LIMIT %s"
    params.append(min(limit, 50))

    conn = get_mysql_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            cursor.execute("SELECT level, COUNT(*) AS c FROM risk_logs GROUP BY level")
            stats = {r["level"]: r["c"] for r in cursor.fetchall()}
    finally:
        conn.close()
    return {"data": rows, "stats": stats, "total": sum(stats.values())}


# =====================================================================
# 个人中心：user_profiles 资料 + Redis 缓存 profile:{昵称}
# =====================================================================
class ProfileIn(BaseModel):
    nickname: str
    school: str = ""
    grade: str = ""
    major: str = ""
    role: str = "freshman"
    goal: str = ""
    email: str = ""


def _read_profile(nickname: str):
    conn = get_mysql_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT nickname, school, grade, major, role, goal, email, updated_at "
                "FROM user_profiles WHERE nickname=%s",
                (nickname,),
            )
            return cursor.fetchone()
    finally:
        conn.close()


@app.get("/profile")
def get_profile(nickname: str):
    """资料卡：Redis → MySQL 缓存旁路（写入后主动失效）"""
    if not nickname.strip():
        raise HTTPException(status_code=400, detail="缺少 nickname 参数")
    cache_key = f"profile:{nickname}"
    t0 = time.perf_counter()
    cached = redis_client.get(cache_key)
    if cached:
        return {"from_cache": True, "cache": cache_flag(cache_key, True, t0), "data": json.loads(cached)}
    row = _read_profile(nickname)
    if not row:
        return {"from_cache": False, "cache": cache_flag(cache_key, False, t0), "data": None}
    redis_client.set(cache_key, json.dumps(row, default=str), ex=1800)
    return {"from_cache": False, "cache": cache_flag(cache_key, False, t0), "data": row}


@app.post("/profile")
def save_profile(p: ProfileIn):
    """完善个人信息：昵称唯一，重复提交按昵称整行更新"""
    nickname = p.nickname.strip()
    if not nickname:
        raise HTTPException(status_code=400, detail="昵称不能为空")
    if len(nickname) > 50:
        raise HTTPException(status_code=400, detail="昵称太长（不超过 50 字）")
    if p.role not in ROLE_ANCHORS:
        raise HTTPException(status_code=400, detail=f"未知身份 {p.role}")

    conn = get_mysql_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO user_profiles (nickname, school, grade, major, role, goal, email)
                VALUES (%s, %s, %s, %s, %s, %s, %s) AS new
                ON DUPLICATE KEY UPDATE
                    school=new.school, grade=new.grade, major=new.major, role=new.role,
                    goal=new.goal, email=new.email
                """,
                (nickname, p.school, p.grade, p.major, p.role, p.goal, p.email),
            )
        conn.commit()
    finally:
        conn.close()

    redis_client.delete(f"profile:{nickname}")
    redis_client.delete(f"briefing:{nickname}")   # 档案变了，个性化简报的排序口径立即作废
    row = _read_profile(nickname)
    for role in ROLE_ANCHORS:
        redis_client.delete(f"path:{role}")   # 身份变了，之前算好的路径缓存全部作废
    return {"ok": True, "data": row}


# =====================================================================
# 模块2 延伸：个人学习清单（study_list）+ AI 排期规划
#   清单是「我想学的」，规划是「图谱前置关系决定必须先学什么」，两者经常不一样：
#   只想打蓝桥杯却没加数据结构，AI 会把数据结构补进计划并说清为什么补
# =====================================================================
PLAN_WEEKS = {"course": 2, "skill": 1, "contest": 3}   # 每类节点占几周（课程最重、技能最快）
STUDY_STATUS = ("todo", "doing", "done")


class StudyIn(BaseModel):
    nickname: str
    node_name: str


class StudyStatusIn(StudyIn):
    status: str = "todo"


def _clean_nickname(nickname: str) -> str:
    nick = (nickname or "").strip()
    if not nick:
        raise HTTPException(status_code=400, detail="缺少 nickname（先在个人中心填个昵称）")
    if len(nick) > 50:
        raise HTTPException(status_code=400, detail="昵称太长（不超过 50 字）")
    return nick


def _study_rows(nickname: str) -> list:
    conn = get_mysql_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT node_name, node_type, status, added_at FROM study_list "
                "WHERE nickname=%s ORDER BY added_at, node_name",
                (nickname,),
            )
            return cursor.fetchall()
    finally:
        conn.close()


@app.get("/study/list")
def my_study_list(nickname: str):
    """我的学习清单：明细 + 三档进度统计（不缓存，加完就要立刻看到）"""
    nick = _clean_nickname(nickname)
    rows = _study_rows(nick)
    return {
        "nickname": nick,
        "total": len(rows),
        "stat": {s: sum(1 for r in rows if r["status"] == s) for s in STUDY_STATUS},
        "data": [{**r, "added_at": str(r["added_at"])} for r in rows],
    }


@app.post("/study/toggle")
def study_toggle(s: StudyIn):
    """图谱上点节点＝加清单，再点一次＝移出（昵称+节点唯一，不会产生重复行）"""
    nick = _clean_nickname(s.nickname)
    name = s.node_name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="缺少 node_name")

    conn = get_mysql_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT name, type FROM kg_nodes WHERE name=%s", (name,))
            node = cursor.fetchone()
            if not node:
                raise HTTPException(status_code=404, detail=f"图谱里还没有「{name}」节点")
            removed = cursor.execute(
                "DELETE FROM study_list WHERE nickname=%s AND node_name=%s", (nick, node["name"]))
            if not removed:                     # 原本不在清单里 → 这次是加入
                cursor.execute(
                    "INSERT INTO study_list (nickname, node_name, node_type) VALUES (%s, %s, %s)",
                    (nick, node["name"], node["type"]))
            added = not removed
        conn.commit()
    finally:
        conn.close()

    redis_client.delete(f"plan:{nick}")         # 清单变了，之前排好的计划必须重算
    rows = _study_rows(nick)
    return {"ok": True, "added": added, "node_name": name, "total": len(rows),
            "data": [{**r, "added_at": str(r["added_at"])} for r in rows]}


@app.post("/study/status")
def study_set_status(s: StudyStatusIn):
    """
    标进度：待学/在学/学完。学完的不再占排期，所以点一下计划就自动往后收。
    AI 补齐的那几步原本不在清单里，但也该能标「我早学过了」——顺手加进清单，别让按钮点了报错
    """
    nick = _clean_nickname(s.nickname)
    name = s.node_name.strip()
    if s.status not in STUDY_STATUS:
        raise HTTPException(status_code=400, detail=f"status 只能是 {'/'.join(STUDY_STATUS)}")
    conn = get_mysql_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT type FROM kg_nodes WHERE name=%s", (name,))
            node = cursor.fetchone()
            if not node:
                raise HTTPException(status_code=404, detail=f"图谱里还没有「{name}」节点")
            cursor.execute(
                """
                INSERT INTO study_list (nickname, node_name, node_type, status)
                VALUES (%s, %s, %s, %s) AS new
                ON DUPLICATE KEY UPDATE status=new.status
                """,
                (nick, name, node["type"], s.status),
            )
        conn.commit()
    finally:
        conn.close()
    redis_client.delete(f"plan:{nick}")
    return {"ok": True, "nickname": nick, "node_name": name, "status": s.status}


def _topo_order(closure: set, prereq_of: dict, dependents: dict, picked: set, layer: dict) -> list:
    """Kahn 拓扑排序：前置=依赖。ready 集按 (层级, 是否自己加的, 名称) 出队，同样输入必得同一份计划"""
    key = lambda n: (layer.get(n, 0), 0 if n in picked else 1, n)
    indeg = {n: len([p for p in prereq_of.get(n, []) if p in closure]) for n in closure}
    ready = sorted([n for n in closure if indeg[n] == 0], key=key)
    order = []
    while ready:
        cur = ready.pop(0)
        order.append(cur)
        for nxt in dependents.get(cur, []):
            if nxt in closure:
                indeg[nxt] -= 1
                if indeg[nxt] == 0:
                    ready.append(nxt)
                    ready.sort(key=key)
    # 图谱里混进环（脏三元组）时拓扑排不完，剩下的按层级补在末尾，宁可多列也不能漏学
    order += sorted(closure - set(order), key=key)
    return order


@app.get("/study/plan")
def study_plan(nickname: str):
    """
    AI 学习规划：清单 → 沿前置边补齐依赖 → 拓扑排序 → 按类型排周 → 大模型写每步理由
    （没配 MAAS_API_KEY 时理由走本地规则，链路一步不少）。结果缓存 plan:{昵称}，10 分钟。
    """
    nick = _clean_nickname(nickname)
    t0 = time.perf_counter()
    cached = redis_client.get(f"plan:{nick}")
    if cached:
        return {"from_cache": True, "cache": cache_flag(f"plan:{nick}", True, t0), **json.loads(cached)}

    rows = _study_rows(nick)
    if not rows:
        raise HTTPException(status_code=400, detail="学习清单还是空的，去知识图谱里点几个节点加进来")

    graph = kg_graph()
    name_of = {n["name"]: n for n in graph["nodes"]}
    prereq_of = _prereq_adj(graph["links"])
    dependents = _dependents_adj(graph["links"])
    picked = {r["node_name"] for r in rows if r["node_name"] in name_of}
    orphans = [r["node_name"] for r in rows if r["node_name"] not in name_of]
    if not picked:
        raise HTTPException(status_code=400,
                            detail="清单里的节点已经不在图谱里了（可能被改名或删掉），请重新点选")

    closure: set = set()
    for target in picked:                        # 每个想学的，把它的全部前置一起拉进来
        closure |= set(_hops_from(target, prereq_of))

    order = _topo_order(closure, prereq_of, dependents, picked,
                        {n["name"]: n["layer"] for n in graph["nodes"]})
    status_of = {r["node_name"]: r["status"] for r in rows}

    profile = _read_profile(nick) or {}
    role = profile.get("role") if profile.get("role") in ROLE_ANCHORS else "freshman"
    done = [n for n in order if status_of.get(n) == "done"]

    steps, week = [], 0
    for n in order:
        if status_of.get(n) == "done":           # 学完的不排期，但它仍是后面的合格前置
            continue
        cost = PLAN_WEEKS.get(name_of[n]["type"], 2)
        week += cost
        steps.append({
            "name": n,
            "type": name_of[n]["type"],
            "description": name_of[n]["description"],
            "layer": name_of[n]["layer"],
            "in_list": n in picked,
            "status": status_of.get(n, "todo"),
            "weeks": cost,
            "week": week,
            "prereq": sorted(p for p in prereq_of.get(n, []) if p in closure),
            "needed_by": sorted(d for d in dependents.get(n, []) if d in closure),
        })

    role_label = ROLE_ANCHORS[role]["label"]
    goal = (profile.get("goal") or "").strip() or ROLE_ANCHORS[role]["target"]
    advice, reasons, engine = ai.plan_study(steps, role_label, goal)
    for i, s in enumerate(steps):
        s["order"] = i + 1
        s["reason"] = reasons.get(s["name"]) or f"按图谱前置关系排在第 {s['order']} 步"

    data = {
        "nickname": nick,
        "role": role,
        "role_label": role_label,
        "goal": goal,
        "engine": engine,
        "advice": advice,
        "steps": steps,
        "done": [{"name": n, "type": name_of[n]["type"]} for n in done],
        "orphans": orphans,
        "list_total": len(rows),
        "total_weeks": week,
    }
    redis_client.set(f"plan:{nick}", json.dumps(data, default=str), ex=600)
    return {"from_cache": False, "cache": cache_flag(f"plan:{nick}", False, t0), **data}

