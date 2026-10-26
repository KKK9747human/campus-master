# 掌控校园 · Campus Master

> 华为云赛题1「校园信息一体化平台」—— 把大学生最头疼的三件事装进一个平台：**该知道什么、该学什么、该防什么**。

**在线演示（静态界面）**：https://kkk9747human.github.io/campus-master/

> GitHub Pages 只是前端静态镜像，后端接口不在线（数据不加载、AI 不出结果，页面底部有提示条）。完整体验请按下面的步骤本地跑起来。

## 功能

| 模块 | 做什么 |
|---|---|
| 📰 AI 情报官 | 学校官方通知源（教务处/招就处/主站）自动抓取聚合、去重入库，AI 一句话摘要强制 `[来源: xx]` 溯源，点得进原文；按个人档案生成个性化简报 |
| 🕸️ 知识图谱 | 经验帖由大模型抽取三元组合并进图谱——图是「长」出来的，不是画出来的；搜索任一概念即以其为中心织出知识网格，沿前置依赖排出学习路径，AI 生成周计划 |
| 🛡️ 安全雷达 | 求职鉴坑 / 聊天鉴诈 / 通知排查三类风险一扫即判；四跳推理链（实体富化→判定→条款检索→链路解释），结论必有编号证据和法条原文，条款库没覆盖就明说，绝不编条款 |
| 💬 经验论坛 | markdown 编辑器 + 配图上传（魔数校验防假图）+ 可运行的代码块（Web Worker 沙箱）+ 草稿自动保存；点赞满 30 自动进精华 |
| 👤 个人中心 | 昵称唯一档案（学校/身份/专业），身份驱动图谱筛选、路径推荐与台账归属 |

## 技术栈

FastAPI · MySQL 8.4（对应华为云 RDS）· Redis（对应 DCS，5 类热点缓存、命中徽章可视化）· MaaS 大模型（OpenAI 兼容接口，**无 Key 自动降级本地规则引擎，断网也能完整演示**）· ECharts · 纯 HTML 前端，零框架零构建

数据库 10 张表：赛题规定的 `notices / posts / kg_nodes / kg_edges` 原样保留，扩展全部在自建表（个人档案、风险台账、条款库、学习清单、通知源、帖子配图）。

## 本地跑起来

环境准备（Python 3.10+ / MySQL / Redis）和详细排错见 **[LOCAL_SETUP.md](LOCAL_SETUP.md)**，最快路径：

```bash
git clone https://github.com/KKK9747human/campus-master.git
cd campus-master
python -m venv venv && venv\Scripts\activate        # Windows
pip install -r requirements.txt

cp .env.example .env                                 # 填入你的 MySQL 密码
mysql -u root -p < sql/init_tables.sql               # 建表（utf8mb4）
python tools_handbook_import.py                      # 灌安全雷达条款库

uvicorn app.main:app --reload --port 8100
```

打开 http://127.0.0.1:8100/ 即是落地页；`/docs` 是 FastAPI 自动生成的接口文档。

五分钟演示动线（建档 → 图谱织网 → 发帖看图谱长节点 → 情报官摘要溯源 → 雷达四跳链路）写在 [LOCAL_SETUP.md](LOCAL_SETUP.md) 第七节。

## 切到华为云

开通 RDS / DCS / MaaS 后**只改 `.env` 三行，代码零改动**，步骤见 [DEPLOY.md](DEPLOY.md)。

## 文档

- [LOCAL_SETUP.md](LOCAL_SETUP.md) — 本地开发指南（安装、建表、演示动线、常见报错）
- [DEPLOY.md](DEPLOY.md) — 华为云部署（Docker / compose / 切云配置）
- [HANDOVER.md](HANDOVER.md) — 开发交接文档（模块实现细节与踩坑记录）
