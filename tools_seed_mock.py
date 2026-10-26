"""
=====================================================================
 掌控校园 —— 学长经验帖 Mock 数据（验证三元组解析 + 路径推荐全链路）
=====================================================================
 用法（项目目录、后端已启动）：
   python tools_seed_mock.py            # 灌入 8 篇示例帖，打印每篇抽取结果 + 三种身份路径
   python tools_seed_mock.py --clean    # 清掉所有"示例·"开头的帖子（图谱节点保留）

 每篇帖子刻意用一种不同的句式，覆盖本地规则引擎的全部抽取模式；
 接上华为云 MaaS Key 后同一批数据还能对比 LLM 与规则引擎的抽取质量。
=====================================================================
"""
import sys

import httpx

BASE = "http://127.0.0.1:8100"

# (标题, 正文, 刻意测试的句式)
MOCK_POSTS = [
    ("考研数学高分经验",
     "考研数学是考研复试的基础，高数和线性代数要先学，学完高数才能学概率论。",
     "A是B的基础 + A要先学B + 学完A才能B"),
    ("冲蓝桥杯的算法路线",
     "想打蓝桥杯算法设计，数据结构要先学，算法设计和数据结构很相关。",
     "A要先学B + A和B很相关"),
    ("英语竞赛备考手记",
     "想参加英语竞赛建议先掌握英语词汇，推荐学完英语听力再练英语口语。",
     "想参加A建议先掌握B + 推荐学完A再学B"),
    ("前端自学路线",
     "学完HTML和CSS才能写JavaScript，JavaScript是React框架的基础。",
     "学完A才能B + A是B的基础"),
    ("后端开发入门",
     "Java基础是后端开发的入门课，学完数据库原理才能做后端开发，操作系统和数据库原理很相关。",
     "A是B的入门 + 学完A才能B + 相关"),
    ("数据分析进阶",
     "概率论是数据分析的基础，学完数据分析才能做机器学习。",
     "A是B的基础 + 学完A才能B"),
    ("大创项目经验",
     "想参加大创项目建议先掌握文献检索，数学建模和大创项目很相关。",
     "想参加A建议先掌握B + 相关"),
    ("ACM 集训队选拔内幕",
     "ACM集训要先学C语言，学完C语言才能学数据结构，离散数学和ACM集训很相关。",
     "混合句式"),
]

ROLE_PATHS = ["freshman", "contest", "jobseeker"]


def seed():
    client = httpx.Client(base_url=BASE, timeout=30)
    print(f"—— 灌入 {len(MOCK_POSTS)} 篇示例经验帖（走 POST /posts 真实解析链路）——\n")
    total_nodes = total_edges = 0
    for title, content, pattern in MOCK_POSTS:
        r = client.post("/posts", json={"title": title, "content": content,
                                        "author": "示例·数据"})
        r.raise_for_status()
        t = r.json()["triples"]
        total_nodes += len(t["nodes"]); total_edges += len(t["edges"])
        print(f"《{title}》 句式[{pattern}] 引擎={t['engine']}")
        for e in t["edges"]:
            print(f"    ✔ {e['source']} —{e['relation']}→ {e['target']}")
        if not t["edges"]:
            print("    ✘ 没抽到任何关系！")
        print()

    g = client.get("/kg/graph").json()
    print(f"—— 图谱规模：{len(g['nodes'])} 节点 / {len(g['links'])} 条边"
          f"（本次新增抽取 {total_nodes} 节点次 / {total_edges} 边次）——\n")

    client.post("/debug/drop-cache")
    print("—— 三种身份的专属学习路径（最短前置链 + 可选支线）——")
    for role in ROLE_PATHS:
        d = client.get(f"/kg/path/{role}").json()["data"]
        chain = " → ".join(s["name"] for s in d["path"])
        print(f"  [{d['role_label']}] {chain}")
        if d["extras"]:
            print(f"      支线可选: {'、'.join(x['name'] for x in d['extras'])}")


def clean():
    """按 source_post_id 溯源级联删除：示例帖 → 抽取产生的节点 → 相关边，演示数据零伤害"""
    import os
    import pymysql
    from dotenv import load_dotenv
    load_dotenv(".env")
    conn = pymysql.connect(
        host=os.getenv("MYSQL_HOST", "127.0.0.1"), user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""), database="campus_master",
        charset="utf8mb4", autocommit=True)
    with conn.cursor() as cur:
        cur.execute("""DELETE e FROM kg_edges e
                       JOIN kg_nodes n ON n.id IN (e.source_node_id, e.target_node_id)
                       JOIN posts p ON p.id = n.source_post_id
                       WHERE p.author LIKE '示例%%'""")
        cur.execute("""DELETE n FROM kg_nodes n
                       JOIN posts p ON p.id = n.source_post_id
                       WHERE p.author LIKE '示例%%'""")
        cur.execute("DELETE FROM posts WHERE author LIKE '示例%%'")
        n = cur.rowcount
    conn.close()
    import redis
    redis.Redis(protocol=2).delete("home:latest_notices", *[f"path:{r}" for r in ROLE_PATHS])
    print(f"已级联删除示例帖及其抽取产生的节点/边（帖子 {n} 篇）")


if __name__ == "__main__":
    if "--clean" in sys.argv:
        clean()
    else:
        seed()
