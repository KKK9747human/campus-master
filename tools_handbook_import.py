"""条款库导入/导出工具（安全雷达的「有理有据」就从这里进库）。

    python tools_handbook_import.py                    # 导入 sql/handbook_articles.json（默认）
    python tools_handbook_import.py --file 我的学校学生手册条款.json
    python tools_handbook_import.py --stats            # 看库里有多少条、几条例还没放开
    python tools_handbook_import.py --export out.json  # 把现有条款导出成同格式，改完再导回来

往库里加本校《学生手册》条款的格式（JSON，UTF-8）：
    {"articles": [{"doc_title": "XX大学学生手册(2024版)", "doc_year": 2024,
                   "article_no": "第六十三条", "title": "出租出借银行卡",
                   "text": "逐字原文，判词里要原样引用，不许改写",
                   "scene": "fraud", "risk_type": "", "keywords": "银行卡,出租,出借",
                   "source": "school", "url": "https://.../xssg.pdf", "trust": 70,
                   "verified": 0, "enabled": 0, "note": "待人工逐字核对"}]}

    scene   job=求职鉴坑 / fraud=聊天鉴诈 / notice=通知排查 / all=通用
    source  law=国家法律 / regulation=部委规章文件 / school=校方手册
    verified=0（还没逐字对上官方原文）或 enabled=0（人工锁定不引用）的行**不会进判词**，
             这是刻意留的门：宁可少一条，不可错一条。
"""
import argparse
import json
import os
import re
import sys

import pymysql
from dotenv import load_dotenv

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FILE = os.path.join(HERE, "sql", "handbook_articles.json")
FIELDS = ["doc_title", "doc_year", "article_no", "title", "text", "scene",
          "risk_type", "keywords", "source", "url", "trust", "verified", "enabled", "note"]
SCENES = ("job", "fraud", "notice", "all")
REQUIRED = ("doc_title", "article_no", "text")


def conn():
    load_dotenv(os.path.join(HERE, ".env"))
    return pymysql.connect(host=os.getenv("MYSQL_HOST", "127.0.0.1"),
                           port=int(os.getenv("MYSQL_PORT", 3306)),
                           user=os.getenv("MYSQL_USER", "root"),
                           password=os.getenv("MYSQL_PASSWORD", ""),
                           database=os.getenv("MYSQL_DATABASE", "campus_master"),
                           charset="utf8mb4")


def drop_clause_cache():
    """雷达把条款库缓存在 Redis handbook:clauses（10 分钟），导完条款必须清掉，
    否则演示时判词引用的还是旧库，改了半天看不出来。"""
    try:
        import redis
        load_dotenv(os.path.join(HERE, ".env"))
        r = redis.Redis(host=os.getenv("REDIS_HOST", "127.0.0.1"),
                        port=int(os.getenv("REDIS_PORT", 6379)),
                        password=os.getenv("REDIS_PASSWORD") or None,
                        protocol=2, socket_connect_timeout=3)
        r.delete("handbook:clauses")
        print("已清掉 Redis 条款缓存 handbook:clauses")
    except Exception as e:
        print(f"（Redis 缓存没清成：{e}；最多 10 分钟后自动过期）")


def normalize(a: dict) -> dict:
    """补齐缺省值并挡掉明显不合格的条款——宁可少一条，不可错一条"""
    for k in REQUIRED:
        if not str(a.get(k) or "").strip():
            raise ValueError(f"缺 {k}")
    scene = (a.get("scene") or "all").strip()
    if scene not in SCENES:
        raise ValueError(f"scene 只能是 {'/'.join(SCENES)}，当前 {scene}")
    text = str(a["text"]).strip()
    if len(text) < 10:
        raise ValueError("原文太短，不像逐字条款")
    return {
        "doc_title": str(a["doc_title"]).strip(),
        "doc_year": a.get("doc_year"),
        "article_no": str(a["article_no"]).strip(),
        "title": str(a.get("title") or "").strip(),
        "text": text,
        "scene": scene,
        "risk_type": str(a.get("risk_type") or "").strip(),
        "keywords": str(a.get("keywords") or "").strip(),
        "source": str(a.get("source") or "law").strip(),
        "url": str(a.get("url") or "").strip() or None,
        "trust": int(a.get("trust") if a.get("trust") is not None else 80),
        "verified": 1 if a.get("verified") else 0,
        # 没核实过的条款一律锁死，光靠 enabled 一个字段把关
        "enabled": 1 if (a.get("enabled") and a.get("verified")) else 0,
        "note": str(a.get("note") or "").strip() or None,
    }


def ensure_table(cur):
    """表不存在就从建表脚本里把这段 DDL 抠出来执行——不在脚本里另抄一份，避免两处 schema 漂移"""
    cur.execute("SHOW TABLES LIKE 'handbook_articles'")
    if cur.fetchone():
        return True
    sql = open(os.path.join(HERE, "sql", "init_tables.sql"), encoding="utf-8").read()
    m = re.search(r"CREATE TABLE IF NOT EXISTS handbook_articles[\s\S]*?COMMENT = '安全雷达条款库[^']*';", sql)
    if not m:
        return False
    cur.execute(m.group(0))
    print("表 handbook_articles 不存在，已按 sql/init_tables.sql 里的 DDL 建好")
    return True


def do_import(path: str):
    if not os.path.exists(path):
        print(f"找不到文件：{path}\n先执行 sql/init_tables.sql 建表，再准备条款 JSON。")
        return 1
    articles = json.loads(open(path, encoding="utf-8").read())
    rows = articles["articles"] if isinstance(articles, dict) else articles
    db, bad = conn(), []
    try:
        with db.cursor() as cur:
            if not ensure_table(cur):
                print("建表失败：sql/init_tables.sql 里找不到表 8 的 DDL。")
                return 1
            added = updated = locked = 0
            for i, raw in enumerate(rows, 1):
                try:
                    r = normalize(raw)
                except ValueError as e:
                    bad.append((i, raw.get("doc_title", "?"), str(e)))
                    continue
                cur.execute(
                    """
                    INSERT INTO handbook_articles
                      (doc_title, doc_year, article_no, title, text, scene, risk_type,
                       keywords, source, url, trust, verified, enabled, note)
                    VALUES (%(doc_title)s, %(doc_year)s, %(article_no)s, %(title)s, %(text)s,
                            %(scene)s, %(risk_type)s, %(keywords)s, %(source)s, %(url)s,
                            %(trust)s, %(verified)s, %(enabled)s, %(note)s)
                    AS new
                    ON DUPLICATE KEY UPDATE
                      doc_year=new.doc_year, title=new.title, text=new.text, scene=new.scene,
                      risk_type=new.risk_type, keywords=new.keywords, source=new.source,
                      url=new.url, trust=new.trust, verified=new.verified,
                      enabled=new.enabled, note=new.note
                    """, r)
                # rowcount: 1=新增，2=更新了旧行，0=内容完全没变
                added += cur.rowcount == 1
                updated += cur.rowcount == 2
                locked += not (r["verified"] and r["enabled"])
            db.commit()
            total = cur.execute("SELECT COUNT(1) FROM handbook_articles") and cur.fetchone()[0]
            live = cur.execute("SELECT COUNT(1) FROM handbook_articles WHERE enabled=1") and cur.fetchone()[0]
        print(f"导入完成：新增 {added} 条、更新 {updated} 条，其中 {locked} 条因未核实被锁住不参与引用")
        print(f"库里现有 {total} 条，参与检索 {live} 条")
        drop_clause_cache()
    finally:
        db.close()
    for i, title, err in bad:
        print(f"  跳过第 {i} 行（{title}）：{err}")
    return 0


def do_stats():
    db = conn()
    try:
        with db.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute("""SELECT scene, source, COUNT(1) AS n,
                                          SUM(enabled=1) AS live, SUM(verified=0) AS unver
                           FROM handbook_articles GROUP BY scene, source ORDER BY scene, source""")
            groups = cur.fetchall()
            cur.execute("SELECT doc_title, COUNT(1) AS n FROM handbook_articles GROUP BY doc_title ORDER BY n DESC")
            docs = cur.fetchall()
            cur.execute("SELECT id, doc_title, article_no, enabled, verified, note FROM handbook_articles "
                        "WHERE enabled=0 OR verified=0 ORDER BY id")
            locked = cur.fetchall()
    finally:
        db.close()
    if not groups:
        print("条款库还是空的，跑一次：python tools_handbook_import.py")
        return 0
    print("场景    来源        条数  参与检索  未核实")
    for g in groups:
        print(f"{g['scene']:<8}{g['source']:<11}{g['n']:>4}  {g['live'] or 0:>7}  {g['unver'] or 0:>5}")
    print("\n按文件：")
    for d in docs:
        print(f"  {d['n']:>3} 条  {d['doc_title']}")
    if locked:
        print("\n锁住不参与引用的（复核后把 verified/enabled 置 1 再导一次）：")
        for x in locked:
            print(f"  #{x['id']} {x['doc_title']} {x['article_no']} — {x['note'] or '未注明原因'}")
    return 0


def do_export(path: str):
    db = conn()
    try:
        with db.cursor(pymysql.cursors.DictCursor) as cur:
            cur.execute(f"SELECT {', '.join(FIELDS)} FROM handbook_articles ORDER BY source, doc_title, id")
            rows = cur.fetchall()
    finally:
        db.close()
    out = {"_说明": "从库里导出来的，改完 doc_title/article_no 之外照原样保留，再 --file 导回即可",
           "articles": rows}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print(f"导出 {len(rows)} 条 → {path}")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="安全雷达条款库导入/导出")
    p.add_argument("--file", default=DEFAULT_FILE, help="条款 JSON 路径（默认 sql/handbook_articles.json）")
    p.add_argument("--stats", action="store_true", help="统计库里条款分布")
    p.add_argument("--export", metavar="OUT.json", help="把现有条款导出成 JSON")
    args = p.parse_args()
    if args.export:
        sys.exit(do_export(args.export))
    if args.stats:
        sys.exit(do_stats())
    sys.exit(do_import(args.file))
