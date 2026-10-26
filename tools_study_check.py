# -*- coding: utf-8 -*-
"""学习清单 + AI 规划接口自测（跑完自动清掉测试昵称的数据）"""
import json
import os
import sys

import httpx

BASE = "http://127.0.0.1:8100"
NICK = "测试·清单号"
failures = []


def check(label, ok, extra=""):
    print(("  [OK]   " if ok else "  [FAIL] ") + label + (f" -> {extra}" if extra else ""))
    if not ok:
        failures.append(label)


def toggle(name, nick=NICK):
    return httpx.post(BASE + "/study/toggle", json={"nickname": nick, "node_name": name}, timeout=20)


print("===== 0. 准备：清掉上次残留 + 给测试昵称建档案 =====")


def db():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import pymysql
    from dotenv import load_dotenv
    load_dotenv()
    return pymysql.connect(host=os.getenv("MYSQL_HOST", "127.0.0.1"),
                           port=int(os.getenv("MYSQL_PORT", 3306)),
                           user=os.getenv("MYSQL_USER", "root"),
                           password=os.getenv("MYSQL_PASSWORD", ""),
                           database=os.getenv("MYSQL_DATABASE", "campus_master"),
                           charset="utf8mb4")


def wipe():
    conn = db()
    with conn.cursor() as cur:
        n1 = cur.execute("DELETE FROM study_list WHERE nickname LIKE '测试·%'")
        n2 = cur.execute("DELETE FROM user_profiles WHERE nickname LIKE '测试·%'")
    conn.commit()
    conn.close()
    return n1, n2


def drop_cache():
    import redis
    from dotenv import load_dotenv
    load_dotenv()
    redis.Redis(host=os.getenv("REDIS_HOST", "127.0.0.1"), port=int(os.getenv("REDIS_PORT", 6379)),
                password=os.getenv("REDIS_PASSWORD") or None, protocol=2
                ).delete(f"plan:{NICK}", "plan:测试·空白号", f"profile:{NICK}", "profile:测试·空白号")


wipe()
drop_cache()
r = httpx.post(BASE + "/profile", json={"nickname": NICK, "grade": "2024级", "major": "信息安全",
                                        "role": "contest", "goal": "蓝桥杯省一"}, timeout=20)
check("建档 200", r.status_code == 200, str(r.status_code))

print("\n===== 1. 加清单（只加目标，让 AI 自己补前置）=====")
r = toggle("蓝桥杯")
check("加「蓝桥杯」返回 added=True", r.status_code == 200 and r.json()["added"] is True, str(r.json())[:120])
r2 = toggle("蓝桥杯")
check("再点一次=移出 added=False", r2.json()["added"] is False and r2.json()["total"] == 0, str(r2.json())[:120])
toggle("蓝桥杯")
check("图谱里没有的节点 404", toggle("量子速读").status_code == 404)
check("空昵称 400", httpx.post(BASE + "/study/toggle", json={"nickname": " ", "node_name": "蓝桥杯"}).status_code == 400)
lst = httpx.get(BASE + "/study/list", params={"nickname": NICK}, timeout=20).json()
check("清单查询到 1 条", lst["total"] == 1 and lst["data"][0]["node_name"] == "蓝桥杯", json.dumps(lst, ensure_ascii=False)[:160])

print("\n===== 2. AI 规划 =====")
p = httpx.get(BASE + "/study/plan", params={"nickname": NICK}, timeout=30)
check("空话：有清单就能出计划", p.status_code == 200, str(p.status_code))
d = p.json()
names = [s["name"] for s in d["steps"]]
print("   身份=%s 目标=%s 引擎=%s 共 %d 步 / %d 周" % (d["role_label"], d["goal"], d["engine"], len(names), d["total_weeks"]))
print("   顺序：", " → ".join(f"{s['name']}(第{s['week']}周{'·自己加的' if s['in_list'] else '·AI补齐'})" for s in d["steps"]))
for s in d["steps"]:
    print(f"     #{s['order']} {s['name']}：{s['reason']}")
print("   整体建议：", d["advice"])
check("AI 自动补齐了没加的前置", any(not s["in_list"] for s in d["steps"]), f"{len(names)} 步里 {sum(1 for s in d['steps'] if not s['in_list'])} 步是补的")
pos = {n: i for i, n in enumerate(names)}
bad = [s for s in d["steps"] for pre in s["prereq"] if pre in pos and pos[pre] >= pos[s["name"]]]
check("前置一定排在后面之前（拓扑正确）", not bad, str([(b["name"], b["prereq"]) for b in bad])[:120])
check("每步都给了理由", all(s.get("reason") for s in d["steps"]))
check("周数递增且 >=1", all(a["week"] < b["week"] for a, b in zip(d["steps"], d["steps"][1:])) and all(s["week"] >= 1 for s in d["steps"]))

print("\n===== 3. 缓存与失效 =====")
c2 = httpx.get(BASE + "/study/plan", params={"nickname": NICK}, timeout=20).json()
check("第二次命中 Redis", c2["from_cache"] is True)
toggle("数据结构")
c3 = httpx.get(BASE + "/study/plan", params={"nickname": NICK}, timeout=30).json()
check("清单变动后缓存作废重算", c3["from_cache"] is False, str(c3["list_total"]))
check("新加的节点变成「自己加的」", any(s["name"] == "数据结构" and s["in_list"] for s in c3["steps"]))

print("\n===== 4. 进度标注 =====")
first = d["steps"][0]["name"]
st = httpx.post(BASE + "/study/status", json={"nickname": NICK, "node_name": first, "status": "done"}, timeout=20)
check(f"把「{first}」标成已学完", st.status_code == 200 and st.json()["status"] == "done", str(st.json())[:100])
c4 = httpx.get(BASE + "/study/plan", params={"nickname": NICK}, timeout=30).json()
check("学完的不再占排期", first not in [s["name"] for s in c4["steps"]] and any(x["name"] == first for x in c4["done"]),
      f"计划 {len(c4['steps'])} 步，已完成 {len(c4['done'])} 项")
check("非法 status 400", httpx.post(BASE + "/study/status", json={"nickname": NICK, "node_name": first, "status": "睡觉"}).status_code == 400)
check("清单里没有的节点 404", httpx.post(BASE + "/study/status", json={"nickname": NICK, "node_name": "没加过", "status": "todo"}).status_code == 404)

print("\n===== 5. 图谱接口按昵称标注清单状态 =====")
g = httpx.get(BASE + "/kg/graph", params={"nickname": NICK}, timeout=20).json()
marked = {n["name"]: (n["in_list"], n["study_status"]) for n in g["nodes"] if n["in_list"]}
check("?nickname= 时节点带 in_list/study_status", bool(marked), json.dumps(marked, ensure_ascii=False)[:160])
g0 = httpx.get(BASE + "/kg/graph", timeout=20).json()
check("不传昵称时全图 in_list=False", not any(n["in_list"] for n in g0["nodes"]))

print("\n===== 6. 空清单/孤儿节点 =====")
httpx.post(BASE + "/profile", json={"nickname": "测试·空白号", "role": "freshman"}, timeout=20)
e = httpx.get(BASE + "/study/plan", params={"nickname": "测试·空白号"}, timeout=20)
check("空清单报 400 并给指引", e.status_code == 400 and "知识图谱" in e.json()["detail"], str(e.json())[:120])
check("缺 nickname 400", httpx.get(BASE + "/study/list", params={"nickname": "  "}, timeout=20).status_code == 400)

print("\n===== 7. 清理测试数据 =====")
n1, n2 = wipe()
drop_cache()
check("清掉测试痕迹", True, f"清单删 {n1} 行，档案删 {n2} 行，plan/profile 缓存已清")

print("\n" + "=" * 56)
print("全部通过：学习清单链路" if not failures else f"失败项 {len(failures)} 个：{failures}")
sys.exit(1 if failures else 0)
