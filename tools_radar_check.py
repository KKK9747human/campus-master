"""安全雷达「多跳 + 有理有据」链路的端到端自检。

    python tools_radar_check.py            # 跑六个用例，逐条打印判定与引用条款
    python tools_radar_check.py --keep     # 跑完不删台账里的测试记录

刻意守住的四条硬规矩（任何一条破了都算 FAIL）：
1. 每一条被引用的条款都必须能在库里查到，且 verified=1 / enabled=1；
2. 每条引用都要有能一眼复核的理由（原文命中词，或风险类型对得上）；
3. 对不上条款的风险必须进 missing_basis，链路里明说「条款库里还没有对得上的条款」，
   没依据就不给置信度——宁可少一条，不可错一条，unknown ≠ safe；
4. 链路文本里不许出现引用清单之外的条款号（防大模型自己编）。
"""
import os
import sys

import httpx

BASE = os.environ.get("CAMPUS_BASE", "http://127.0.0.1:8100")
NICK = "测试·雷达"
HERE = os.path.dirname(os.path.abspath(__file__))

CASES = [
    ("job", "HR同学你好~ 线上运营兼职日薪300，轻松月入过万！入职前需要交200元押金作为服装费，"
            "不用签合同的，都是口头约定，先把身份证原件发我登记，另外要参加3天培训，培训费199。"),
    ("fraud", "兄弟，把你的银行卡和手机卡借我走几天流水，一天给你150报酬，就过一下账，"
              "跟你没关系的事。微信账号也能借两天，一个号再加200，别跟别人讲啊。"),
    ("fraud", "我是你辅导员李老师，学院给你办了奖学金退税，把手机收到的验证码发我一下，"
              "再点这个链接 http://jsxy-award.top/register 填银行卡，今天不办就作废。"),
    ("fraud", "学长说带我在这个投资平台内幕稳赚，先投5000，日入过千，稳赚不赔，别跟别人讲。"),
    ("notice", "【教务处通知】2026 年奖学金退税补贴开始发放，请所有获奖同学 24 小时内点击 "
               "http://ehall-jsxx.vip/tax 填写银行卡与身份证信息，逾期视为自动放弃。"),
    ("job", "同学你好，我们社团招新，周末在操场摆摊，有兴趣可以直接过来聊聊。"
            "没有任何费用，也不用交材料，来的时候带学生证看一下就行。"),
]

fails = []


def check(name, ok, detail=""):
    print(f"  {'✓' if ok else '✗ FAIL'} {name}{('  → ' + detail) if detail else ''}")
    if not ok:
        fails.append(name)


def db():
    import pymysql
    from dotenv import load_dotenv
    load_dotenv(os.path.join(HERE, ".env"))
    return pymysql.connect(host=os.getenv("MYSQL_HOST", "127.0.0.1"),
                           port=int(os.getenv("MYSQL_PORT", 3306)),
                           user=os.getenv("MYSQL_USER", "root"),
                           password=os.getenv("MYSQL_PASSWORD", ""),
                           database=os.getenv("MYSQL_DATABASE", "campus_master"),
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)


def load_library():
    """库里实况：citable = 允许被引用的条款，作为引用真伪的唯一裁判"""
    with db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT doc_title, article_no, scene, risk_type, verified, enabled "
                        "FROM handbook_articles")
            rows = cur.fetchall()
    key = lambda r: f"{r['doc_title']} {r['article_no']}"
    citable = {key(r) for r in rows if r["verified"] and r["enabled"]}
    types = {key(r): (r["risk_type"] or "") for r in rows}
    return rows, citable, types


def run_case(client, idx, scene, text, citable, types):
    r = client.post(f"{BASE}/safety/scan",
                    json={"text": text, "scene": scene, "nickname": NICK}, timeout=40)
    r.raise_for_status()
    d = r.json()
    risks, clauses = d.get("risks", []), d.get("clauses", [])
    by_no = {c["no"]: c for c in clauses}
    missing = {m["risk_index"] for m in d.get("missing_basis", [])}

    print(f"\n[{d.get('scene')}] {d.get('level')} {d.get('score')} 分 · "
          f"置信度 {d.get('confidence', {}).get('value')}")
    print(f"  结论：{d.get('verdict')}")
    for c in clauses:
        print(f"  C{c['no']} {c['doc_title']} {c['article_no']} [{c['source_label']}] "
              f"命中={c['matched'] or '按风险类型对齐'}")
    for h in d.get("chain", []):
        print(f"  第{h['hop']}跳 {h['name']}({h['engine']})：{h['summary']}")

    tag = f"#{idx} {scene}·"
    check(tag + "判级合法", d.get("level") in
          ("high_risk", "medium_risk", "low_risk", "likely_safe"))
    check(tag + "四跳齐全", len(d.get("chain", [])) == 4)

    ghost = [c["no"] for c in clauses if f"{c['doc_title']} {c['article_no']}" not in citable]
    check(tag + "引用都能回溯到已核实条款", not ghost, f"清单外：{ghost}")

    unjust = []
    for r_ in risks:
        for no in r_.get("basis", []):
            c = by_no[no]
            if c["matched"] or r_.get("type", "") in types.get(f"{c['doc_title']} {c['article_no']}", ""):
                continue
            unjust.append(f"C{no}/{r_.get('type')}")
    check(tag + "每条引用都有可复核理由", not unjust, f"无理由：{unjust}")

    no_basis = {x["no"] for x in risks if not x.get("basis")}
    check(tag + "无依据的风险如实弃权", no_basis == missing,
          f"risks={sorted(no_basis)} missing={sorted(missing)}")

    if not clauses:
        check(tag + "无条款时不给置信度", d.get("confidence", {}).get("value") is None)
        if risks:   # 有真风险却没依据 → 必须挑明「没有条款」；压根没风险 → 必须挑明「不等于安全」
            check(tag + "有风险无依据时结论挑明", "条款" in (d.get("verdict") or ""))
        else:
            check(tag + "判safe时不宣称安全", "不等于安全" in (d.get("verdict") or ""))

    allowed = [f"{c['doc_title']}{c['article_no']}" for c in clauses]
    invented = []
    for line in d.get("chain", [])[3].get("items", []):
        if "对应" not in line:
            continue
        tail = line.split("对应", 1)[1].strip()
        if not any(tail.endswith(a) for a in allowed):
            invented.append(tail)
    check(tag + "链路只引用清单内条款号", not invented, f"编造：{invented}")
    check(tag + "写入台账", bool(d.get("log_id")))
    return d


def main():
    keep = "--keep" in sys.argv
    rows, citable, types = load_library()
    with httpx.Client(timeout=40) as client:
        h = client.get(f"{BASE}/health").json()
        print("health:", h)
        check("服务与 MySQL/Redis 在线",
              h.get("mysql") == "connected" and h.get("redis") == "connected")

        results = [run_case(client, i, s, t, citable, types)
                   for i, (s, t) in enumerate(CASES, 1)]
        cited = lambda d: {f"{c['doc_title']} {c['article_no']}" for c in d["clauses"]}

        check("求职押金 → 劳动合同法第九条",
              "中华人民共和国劳动合同法 第九条" in cited(results[0]))
        check("借银行卡 → 反电诈法第三十一条",
              "中华人民共和国反电信网络诈骗法 第三十一条" in cited(results[1]))
        check("索要验证码 → 反电诈法第二十五条",
              "中华人民共和国反电信网络诈骗法 第二十五条" in cited(results[2]))
        check("投资荐股 → 如实说条款库未覆盖",
              bool(results[3]["missing_basis"]) and not results[3]["clauses"],
              f"missing={results[3]['missing_basis']}")
        check("通知退税 → 有中危判级", results[4]["level"] in ("medium_risk", "high_risk"))
        check("正常社团招新 → 不硬凑依据",
              results[5]["level"] == "likely_safe" and not results[5]["clauses"])

        hb = client.get(f"{BASE}/safety/handbook", params={"limit": 100}).json()
        st = hb["stats"]
        check("条款库统计=库里实况",
              st["total"] == len(rows) and st["citable"] == len(citable),
              f"接口 {st['citable']}/{st['total']}，库 {len(citable)}/{len(rows)}")
        check("未核实的条款进不了判词", all(
            f"{x['doc_title']} {x['article_no']}" not in citable for x in st["locked"]))

        logs = client.get(f"{BASE}/safety/logs", params={"nickname": NICK, "limit": 50}).json()
        check("台账留得住引用条款",
              any(r.get("cited_articles") for r in logs["data"]),
              f"{sum(1 for r in logs['data'] if r.get('cited_articles'))} 条带条款")

        if not keep and logs["data"]:
            with db() as conn:
                with conn.cursor() as cur:
                    n = cur.execute("DELETE FROM risk_logs WHERE nickname=%s", (NICK,))
                conn.commit()
            print(f"\n已清掉本次 {n} 条测试台账（演示只留 init_tables.sql 里那 4 条【演示数据】）")

    print("\n" + ("全部通过：安全雷达多跳链路" if not fails else f"{len(fails)} 项未通过：{fails}"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
