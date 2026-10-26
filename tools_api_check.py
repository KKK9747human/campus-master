# -*- coding: utf-8 -*-
"""
全接口冒烟测试：后端起来后跑一遍，确认「安全雷达 / 个人中心 / 论坛 / 图谱分层」四条链路都通。

    venv/Scripts/python tools_api_check.py            # 对本地 8100
    BASE=http://127.0.0.1:8000 venv/Scripts/python tools_api_check.py   # 换端口

脚本自己造的测试数据（昵称一律带「测试·」前缀，测试帖走点赞数还原）跑完当场清干净，
不给演示库留仿真痕迹。
"""
import os
import sys

import httpx

BASE = os.getenv("BASE", "http://127.0.0.1:8100")
TEST_NICK = "测试·冒烟号"

JOB = "HR同学你好~ 我们线上运营兼职日薪300，轻松月入过万！入职前要交200元押金，不用签合同的。"
FRAUD = ("同学我是辅导员，你的助学金需要现在点开 http://jsxy-claim.top 领取，"
         "把短信验证码发我核实一下，马上截止，别告诉其他同学。")
NOTICE = "【教务处通知】明天选课系统维护，请所有同学登录 http://ehall-xxx.vip 填写银行卡信息领取退税。"
SAFE = "周末社团纳新在操场摆摊，有兴趣的同学可以直接过来找我聊，不用交任何费用。"

failures = []


def check(label, ok, detail=""):
    print(("  [OK]  " if ok else "  [FAIL]") + f" {label}" + (f" -> {detail}" if detail else ""))
    if not ok:
        failures.append(label)


print(f"\n===== 1. 图谱分层数据（{BASE}）=====")
g = httpx.get(BASE + "/kg/graph", params={"role": "contest"}, timeout=20).json()
check("带 role 的图返回 goal", g.get("goal") == "蓝桥杯", g.get("goal"))
check("节点带 layer/on_path/hop", all({"layer", "on_path", "hop"} <= set(n) for n in g["nodes"]),
      f"{len(g['nodes'])} 个节点")
by_name = {n["name"]: n for n in g["nodes"]}
bad = [f'{l["source"]}->{l["target"]}' for l in g["links"]
       if l["relation"] == "prerequisite" and l["source"] in by_name and l["target"] in by_name
       and by_name[l["source"]]["layer"] >= by_name[l["target"]]["layer"]]
check("前置边一定从左列指向右列", not bad, bad or "0 条违规")
on = [n["name"] for n in g["nodes"] if n["on_path"]]
check("身份筛选只剩通往锚点的前置子图", set(on) == {"C语言", "数据结构", "蓝桥杯"}, on)

print("\n===== 2. 四种身份的学习路径 =====")
for role, anchor in [("freshman", "数据结构"), ("contest", "蓝桥杯"),
                     ("jobseeker", "实习"), ("postgrad", "考研复试")]:
    r = httpx.get(BASE + f"/kg/path/{role}", timeout=20)
    if r.status_code != 200:
        check(f"/kg/path/{role}", False, f"{r.status_code} {r.text[:80]}")
        continue
    p = r.json()["data"]
    chain = " → ".join(s["name"] for s in p["path"])
    check(f"{role} 主线终点是 {anchor} 且不止一个节点",
          p["goal"] == anchor and len(p["path"]) >= 2 and p["path"][-1]["name"] == anchor, chain)
check("未知身份 404", httpx.get(BASE + "/kg/path/alien").status_code == 404)

print("\n===== 3. 安全雷达三场景 =====")
for label, text, want_scene, want_level in [
    ("求职鉴坑", JOB, "job", "high_risk"),
    ("聊天鉴诈", FRAUD, "fraud", "high_risk"),
    ("通知排查", NOTICE, "notice", "high_risk"),
    ("干净内容不误伤", SAFE, "fraud", "likely_safe"),
]:
    d = httpx.post(BASE + "/safety/scan", json={"text": text, "nickname": TEST_NICK}, timeout=30).json()
    check(f"{label} → scene={want_scene} level={want_level}",
          d.get("scene") == want_scene and d.get("level") == want_level,
          f'{d.get("scene_label")}/{d.get("level")}/{d.get("score")}分，命中 {len(d.get("risks", []))} 条')
    if want_level != "likely_safe":
        check("  每条风险都带原文证据",
              all(r.get("quote") for r in d.get("risks", [])),
              [r["type"] for r in d.get("risks", [])])
check("短文本 400", httpx.post(BASE + "/safety/scan", json={"text": "太短"}).status_code == 400)

logs = httpx.get(BASE + "/safety/logs", params={"nickname": TEST_NICK}, timeout=20).json()
check("台账按昵称过滤", len(logs["data"]) == 4, f'{len(logs["data"])} 条，总计 {logs["total"]} 条')
check("台账等级统计", sum(logs["stats"].values()) >= 4, logs["stats"])

print("\n===== 4. 个人中心 =====")
p = httpx.post(BASE + "/profile", json={"nickname": TEST_NICK, "grade": "2024级",
                                        "major": "计算机科学与技术", "role": "contest",
                                        "goal": "蓝桥杯省一", "email": "smoke@example.edu.cn"},
               timeout=20).json()
check("建档", p.get("ok") and p["data"]["role"] == "contest", p.get("data"))
p2 = httpx.post(BASE + "/profile", json={"nickname": TEST_NICK, "grade": "2024级",
                                         "major": "计算机科学与技术", "role": "jobseeker",
                                         "goal": "大三暑期实习", "email": "smoke@example.edu.cn"},
                timeout=20).json()
check("同昵称再提交=整行更新（不产生第二份档案）",
      p2["data"]["role"] == "jobseeker" and p2["data"]["goal"] == "大三暑期实习", p2["data"])
g1 = httpx.get(BASE + "/profile", params={"nickname": TEST_NICK}, timeout=20).json()
g2 = httpx.get(BASE + "/profile", params={"nickname": TEST_NICK}, timeout=20).json()
check("读取走缓存旁路 miss→hit", g1["from_cache"] is False and g2["from_cache"] is True,
      f'miss={g1["from_cache"]} hit={g2["from_cache"]}')
check("查不存在的昵称返回 null 不报错",
      httpx.get(BASE + "/profile", params={"nickname": "测试·查无此人"}).json()["data"] is None)
check("非法身份 400", httpx.post(BASE + "/profile", json={"nickname": TEST_NICK, "role": "alien"}).status_code == 400)
check("空昵称 400", httpx.post(BASE + "/profile", json={"nickname": "  "}).status_code == 400)

print("\n===== 5. 论坛筛选 / 精华 / 点赞 =====")
allp = httpx.get(BASE + "/posts/latest", params={"limit": 50}, timeout=20).json()
line = allp["essence_line"]
check("精华线由点赞阈值判定", all(bool(p["is_essence"]) == (p["likes"] >= line) for p in allp["data"]),
      f"阈值 {line}，{sum(p['is_essence'] for p in allp['data'])}/{len(allp['data'])} 篇精华")
ess = httpx.get(BASE + "/posts/latest", params={"filter": "essence", "limit": 50}, timeout=20).json()
check("精华页签全部达线", all(p["likes"] >= line for p in ess["data"]), f"{len(ess['data'])} 篇")
check("精华按点赞降序", [p["likes"] for p in ess["data"]] == sorted((p["likes"] for p in ess["data"]), reverse=True),
      [p["likes"] for p in ess["data"]])
kw = httpx.get(BASE + "/posts/latest", params={"keyword": "蓝桥杯", "limit": 50}, timeout=20).json()
check("关键词搜索命中", len(kw["data"]) >= 1 and all("蓝桥杯" in (p["title"] + p["content"]) for p in kw["data"]),
      [p["title"] for p in kw["data"]])
check("mine 缺 author 报 400", httpx.get(BASE + "/posts/latest", params={"filter": "mine"}).status_code == 400)

pid = allp["data"][0]["id"]
before_likes = allp["data"][0]["likes"]
liked = httpx.post(BASE + f"/posts/{pid}/like", timeout=20).json()
check("点赞 +1", liked["likes"] == before_likes + 1, f'{before_likes} → {liked["likes"]}')
check("点赞不存在的帖 404", httpx.post(BASE + "/posts/999999/like").status_code == 404)

# ---- 收尾：把测试痕迹清干净，演示库只留「一眼假」的示例数据 ----
print("\n===== 6. 清理测试数据 =====")
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import pymysql
    from dotenv import load_dotenv
    load_dotenv()
    conn = pymysql.connect(host=os.getenv("MYSQL_HOST", "127.0.0.1"),
                           port=int(os.getenv("MYSQL_PORT", 3306)),
                           user=os.getenv("MYSQL_USER", "root"),
                           password=os.getenv("MYSQL_PASSWORD", ""),
                           database=os.getenv("MYSQL_DATABASE", "campus_master"),
                           charset="utf8mb4")
    with conn.cursor() as cur:
        cur.execute("UPDATE posts SET likes=%s WHERE id=%s", (before_likes, pid))
        cur.execute("DELETE FROM risk_logs WHERE nickname=%s", (TEST_NICK,))
        n_log = cur.rowcount
        cur.execute("DELETE FROM user_profiles WHERE nickname=%s", (TEST_NICK,))
        n_pro = cur.rowcount
    conn.commit()
    conn.close()
    print(f"  点赞已还原（#{pid} → {before_likes}），台账删 {n_log} 行，档案删 {n_pro} 行")
    import redis as _redis
    _redis.Redis(host=os.getenv("REDIS_HOST", "127.0.0.1"), port=int(os.getenv("REDIS_PORT", 6379)),
                 password=os.getenv("REDIS_PASSWORD") or None, protocol=2).delete(f"profile:{TEST_NICK}")
    print("  profile 缓存已清")
except Exception as e:
    check("清理测试数据", False, str(e))

print("\n" + "=" * 56)
print(("全部通过：" if not failures else "失败项：") + (f"{len(failures)} 个" if failures else "15+ 项链路"))
for f in failures:
    print("  - " + f)
print("=" * 56)
sys.exit(1 if failures else 0)
