# 掌控校园 · 本地开发指南（离线版）

> 目标：不依赖任何云服务，在你自己的电脑上跑通整个项目。
> 未来切到华为云 RDS + Redis 时，**只改 `.env` 一个文件，代码零改动**。
> 预计耗时：全部装完 30~60 分钟（主要是下载安装包的时间）。

---

## 〇、你会得到的项目结构

```
campus-master/
├── requirements.txt        # 依赖清单
├── .env                    # 数据库连接配置（要填密码的就是它）
├── .env.example            # 配置模板（华为云占位符版）
├── .gitignore
├── LOCAL_SETUP.md          # 本文件
├── sql/
│   └── init_tables.sql     # 建表脚本（赛题4张 + 扩展2张）+ 演示数据
├── app/
│   ├── __init__.py
│   ├── main.py             # FastAPI 后端入口：接口 + MySQL/Redis 读写 + 图谱算法
│   └── ai.py               # AI 能力层：MaaS 大模型调用 + 本地规则引擎降级
├── tools_seed_mock.py      # 灌/清 8 篇 mock 学长帖，验证三元组解析链路
├── tools_api_check.py      # 全接口冒烟测试：后端起来后 `python tools_api_check.py` 一遍过一遍所有接口
├── web/
│   ├── common.css          # 全站统一样式（顶栏五页导航、卡片、徽章、台账表格）
│   ├── echarts.min.js      # 本地化的 ECharts，断网也能画图
│   ├── notice.html         # 模块1 AI 校园情报官
│   ├── kg_demo.html        # 模块2 知识图谱 + 分层视图 + 身份筛选 + 学习路径
│   ├── forum.html          # 模块2 经验论坛（全部/精华/我的 + 发帖抽三元组）
│   ├── safety.html         # 模块3 安全雷达（求职鉴坑/聊天鉴诈/通知排查 + 风险台账）
│   ├── profile.html        # 个人中心（资料卡 + 我的发帖 + 我的风险记录）
│   └── echarts_demo.html   # 最初的四节点力导向 Demo（学 ECharts 时用，不进导航）
└── _archive/
    └── job_radar.html      # 旧版独立「防坑雷达」页，功能已并入 safety.html
```


---

## 一、安装 Python（3.10 及以上版本）

**Windows：**
1. 打开官网 https://www.python.org/downloads/ 下载最新版安装包
2. 双击安装，**第一屏务必勾选 `Add python.exe to PATH`**（90% 的新手报错都因为漏了它）
3. 验证：按 `Win + R` 输入 `cmd` 回车，在黑窗口里输入：

```bash
python --version
```

看到 `Python 3.12.x` 之类输出即成功。

**macOS：**
```bash
brew install python@3.12
python3 --version
```

> 下文 Windows 命令用 `python`，macOS 用 `python3`，注意区分。

---

## 二、安装本地 MySQL（代替华为云 RDS）

**Windows：**
1. 官网下载 `MySQL Installer`（社区版，搜索 "MySQL Installer" 进入官网 Community 页）
2. 安装时 Setup Type 选 **`Server only`**，其余一路默认（端口 3306 不改）
3. 设置 root 密码时**用一个你绝不会忘的密码**（比如和微信不一样的生日+姓名缩写）
4. 安装完成后 MySQL 会作为 `MySQL80` 服务自动在后台运行

**macOS：**
```bash
brew install mysql
mysql.server start          # 手动启动（重启电脑后需再执行）
mysqladmin -u root password '你的新密码'   # 给 root 设个密码
```

**验证（Windows）：** `Win + R` → 输入 `services.msc` 回车 → 列表里找到 `MySQL80`，状态应为"正在运行"。

---

## 三、安装本地 Redis（代替华为云 DCS）

**Windows（官方不支持，用社区移植版，5 分钟搞定）：**
1. 打开 GitHub 搜索 `tporadowski/redis`（或直接访问 github.com/tporadowski/redis/releases）
2. 下载 `Redis-x64-5.0.14.1.zip`，解压到好找的位置，如 `C:\redis`
3. 双击 `redis-server.exe` —— **弹出的黑窗口必须保持开着**，关掉 = Redis 停了
4. 验证：双击 `redis-cli.exe`，输入 `ping`，返回 `PONG` 即成功

**macOS：**
```bash
brew install redis
brew services start redis   # 开机自启
redis-cli ping              # 应返回 PONG
```

---

## 四、解压项目 + 装依赖

把 `campus-master.zip` 解压到好找的位置，如 `D:\projects\campus-master`。

打开命令行并进入项目目录（Windows 示例）：

```bash
D:
cd D:\projects\campus-master
```

创建虚拟环境（= 项目的"独立房间"，避免搞乱系统）：

```bash
python -m venv venv
venv\Scripts\activate        # Windows 激活
# macOS 激活命令是: source venv/bin/activate
```

激活成功的标志：命令行最前面多了个 `(venv)` 前缀。

安装依赖（用华为云镜像，和云端同一来源）：

```bash
pip install -r requirements.txt -i https://repo.huaweicloud.com/repository/pypi/simple
```

---

## 五、改配置文件（填你的 MySQL 密码）

用记事本或 VS Code 打开项目根目录的 `.env`，把这一行改掉：

```
MYSQL_PASSWORD=在这里填你安装MySQL时设置的root密码
```

Redis 那两行不用动（本地 Redis 无密码、默认端口）。

---

## 六、建表（执行 SQL 脚本）

**方式 A：命令行（推荐，一条命令）**

```bash
mysql -u root -p < sql\init_tables.sql
```
回车后输入你的 root 密码。没有任何报错输出 = 成功。

**方式 B：图形化工具（命令行报错/不习惯的用这个）**

1. 下载安装 `MySQL Workbench`（官方免费图形化客户端）或 `DBeaver`
2. 新建连接：主机 `127.0.0.1`、端口 `3306`、用户 `root`、密码 = 你的密码
3. 菜单 `File → Open SQL Script` 选择 `sql/init_tables.sql`
4. 点闪电图标 ⚡ 执行

**验证数据进去了：** 执行 `mysql -u root -p -e "USE campus_master; SELECT * FROM notices;"` 能看到两条演示通知。

**一共 8 张表**：赛题规定的 `notices / posts / kg_nodes / kg_edges` 字段一个没动，
另外四张 `user_profiles`（个人中心）、`risk_logs`（安全雷达台账，含 `cited_articles` 引用条款列）、
`study_list`（个人学习清单）、`handbook_articles`（安全雷达条款库）是我自己加的扩展表，
不掺进赛题表里，评委按赛题清单核对时不会被干扰。

**建完表还要灌条款库**（`handbook_articles` 建表时是空的，雷达没条款就只能弃权）：

```bash
python tools_handbook_import.py     # 导入 sql/handbook_articles.json：34 条，可引用 31 条
python tools_handbook_import.py --stats
```

---

## 七、启动！验证！

在项目目录（记得 venv 已激活）执行：

```bash
uvicorn app.main:app --reload --port 8000
```

看到 `Uvicorn running on http://127.0.0.1:8000` 即启动成功。
（`--reload` 的意思：改完代码自动重启，开发期必加；停止服务按 `Ctrl + C`）

**逐项验证（这步最有成就感）：**

| 打开什么 | 期待看到什么 |
|---|---|
| http://127.0.0.1:8000/health | `"mysql": "connected"` 且 `"redis": "connected"` |
| http://127.0.0.1:8000/docs | FastAPI 自动生成的接口测试页 |
| /docs 里测 `GET /notices/latest` | `from_cache: false` + 两条演示通知 |
| **刷新**再测一次 `GET /notices/latest` | `from_cache: true` —— 这就是 Redis 缓存在干活！ |
| 双击 `web/echarts_demo.html` | 四个圆圈连成网的力导向图，可拖拽缩放 |

> **端口被占用怎么办？** 本机 8000 端口若已被别的服务占用（`Error 10048`），
> 换 `--port 8100` 启动即可，下面所有 `:8000` 同步换成 `:8100`。
> **改完代码不生效？** 本机实测 uvicorn `--reload` 监听不到 D 盘的文件变化，
> 改过后端代码后 Ctrl+C 重启一次即可。

---

## 七点五、六个页面的演示路线（后端已实现，直接访问）

| 页面 | 能演示什么 |
|---|---|
| `http://127.0.0.1:8100/` | 评委落地页：一句话故事 + 三模块一句话卡 + 华为云服务映射 + 技术栈跑马灯；右上角 MySQL/Redis 实时状态灯（完整演示动线与 AI 降级说明见下文，不再堆在首页） |
|---|---|
| `http://127.0.0.1:8100/web/notice.html` | 模块1：**官方源聚合为主信源**（按档案里的学校抓学校通知公告/教务处/就业中心列表页，标题+链接入库可溯源，点「AI 一句话」才抓详情页生成摘要）；手动贴入降为兜底（AI 摘要+强制溯源 `[来源: xx]`）；首页缓存失效重建 |
| `http://127.0.0.1:8100/web/kg_demo.html` | 模块2：图谱**分层视图**（列号=学习先后）+ 按身份筛选 + 力导向切换 + 学习路径（Redis 缓存）+ **点节点聚焦、加入学习清单、AI 排周计划** |
| `http://127.0.0.1:8100/web/forum.html` | 模块2 数据来源：全部/精华/我的三个页签 + 关键词搜索 + 点赞；发帖支持**标题/加粗/引用/列表/代码 + 配图**（选图/拖拽/粘贴，存 `uploads/` + `post_media` 表），发布即抽三元组入图谱 |
| `http://127.0.0.1:8100/web/safety.html` | 模块3：求职鉴坑 / 聊天鉴诈 / 通知排查 三场景一处入口，**四跳推理链 + 编号证据 E→依据 C + 条款逐字原文与权威链接 + 置信度**，查不到条款就明说「条款库未覆盖」；页底可翻条款库、台账记引用（MySQL `risk_logs`） |
| `http://127.0.0.1:8100/web/profile.html` | 个人中心：填昵称/身份/专业存 MySQL `user_profiles`，右侧资料卡 + 我的发帖 + 我的风险记录 |

**演示动线（五步，约 5 分钟）**：
① 个人中心建档：昵称 `计科2301张同学`，身份选「竞赛选手」，右侧资料卡即时更新；
② 知识图谱：搜「蓝桥杯」织出知识网格 → 点节点换中心 → 「加入我的学习清单」→ 「✨ AI 生成学习规划」看它沿前置边补齐依赖、排到第几周；
③ 论坛发帖：写一篇经验帖（支持 markdown / 配图 / 可运行的代码块），发布即抽三元组，回图谱看它长出新节点；
④ 情报官：拉取学校官方通知 → 点「AI 一句话」看溯源摘要 → 点标题跳原文；
⑤ 安全雷达：粘一段 HR 聊天记录，看四跳链路 + 编号证据 + 法条原文，台账里多一条记录。

**缓存策略肉眼验法**：`POST /debug/drop-cache`（在 /docs 里点即可）清空全部缓存后，
去情报官/图谱/个人中心刷新，徽章会从「Redis 缓存命中」变成「查 MySQL 并回填缓存」，
再刷一次又变回命中——赛题要求的缓存读写策略当场可验。

**AI 引擎说明**：`.env` 里 `MAAS_API_KEY` 留空时，`app/ai.py` 自动降级到内置
「本地规则引擎」（页面上会显示"本地规则引擎"标签），断网也能完整演示；
拿到华为云 MaaS 的 Key 后填进 `.env` 即无缝切到大模型，代码零改动。

主要接口：

| 接口 | 用途 |
|---|---|
| `GET /notices/sources`、`POST /notices/fetch?school=`、`GET /notices/official`、`POST /notices/{id}/summarize` | 模块1 主链路：官方源清单 / 抓列表页去重入库 / 官方通知列表 / 按需抓详情页生成一句话摘要 |

官方源**定时自动抓取**已内置：后端启动即有后台守护线程，每 `FETCH_INTERVAL_MINUTES`
分钟（.env 可配，默认 30，0=关闭）自动对所有启用源各抓一轮，与手动按钮走同一套
`run_official_fetch`，日志前缀 `[fetch-cron]`（uvicorn.log 可查）。
| `POST /notices/ai`、`GET /notices/latest`、`GET /notices/{id}` | 模块1 兜底：贴原文抽取入库 + 首页缓存 |
| `GET /notices/briefing?nickname=` | 情报官个性化简报：按档案打分（代码算，命中词可回溯）→ AI 整合导语 + 通知↔图谱概念织网链接（`briefing:{昵称}` 缓存 600s） |
| `POST /upload`、`POST /posts`、`GET /posts/latest`、`POST /posts/{id}/like` | 模块2 配图上传（魔数校验 5MB）/ 发帖抽三元组（可带 `images`）/ 论坛筛选 / 点赞 |
| `GET /kg/graph?role=&nickname=`、`GET /kg/path/{role}` | 模块2 图谱数据（节点/边 + 清单标注；`role` 仍供路径接口用）/ 学习路径 |
| `POST /study/toggle`、`GET /study/list`、`POST /study/status`、`GET /study/plan` | 模块2 学习清单增删 / 明细 / 标进度 / AI 排周计划 |
| `POST /safety/scan`、`GET /safety/skills`、`GET /safety/logs`、`GET /safety/handbook` | 模块3 三场景四跳风控（富化→判定→条款检索→链路解释）+ 可选检测技能（条款库提炼，锁定依据池）+ 风险台账 + 条款库浏览 |
| `GET /profile`、`POST /profile` | 个人中心资料（`profile:{昵称}` 走 Redis 缓存） |
| `POST /debug/drop-cache` | 演示辅助：清掉全部缓存，现场演示 miss→查库→回填 |

`role` 可选 `freshman`（大一新生→数据结构）/ `contest`（竞赛选手→蓝桥杯）/
`jobseeker`（求职党→实习）/ `postgrad`（考研党→考研复试）。
`GET /posts/latest` 的 `filter` 可选 `all`/`essence`/`mine`，精华按点赞数阈值判定
（`main.py` 的 `ESSENCE_LIKES = 30`），**不改赛题规定的 `posts` 表结构**。

---

## 七点六、mock 学长经验帖（演示前灌数据用）

```bash
python tools_seed_mock.py           # 灌 8 篇示例帖，逐篇打印抽到的三元组 + 三种身份路径
python tools_seed_mock.py --clean   # 按 source_post_id 级联删掉示例帖及其产生的节点/边
```

8 篇帖子每篇刻意用一种句式（`A要先学B`、`学完A才能B`、`A是B的基础`、`想参加A建议先掌握B`、
`A和B很相关`、`推荐学完A再学B`），作者统一是 `示例·数据`，真机演示时一眼就能认出是假数据，
`--clean` 也能精准清干净、不碰手工演示数据。

图谱页这几个渲染坑（改前端容易再踩，写在这省得重新查）：
- 节点必须剔掉数据库 `id` 再交给 ECharts，否则 links 按 `name` 引用的端点会被按 `id` 解析，**所有关系线静默消失**；
- `fitView` 只按力导向仿真**第一帧**取景，而仿真是继续往外扩散的，跑完节点就顶出画布。
  所以 `kg_demo.html` 里等 1.8s 后用 `fitToCanvas()` 量真实包围盒重新缩放+居中（缩放下限锁 0.85，
  再小标签字号不跟着缩就会糊），窗口 resize 时同样重算；
- 边上的关系名默认不上图（22 条边各带 60~90px 的标签是画面糊掉的主因），悬停连线才显示，
  平时靠线色/线型区分：实线=前置、虚线=相关、紫线=包含，卡片上方的图例已写明；
- **分层视图：ECharts 会把「坐标包围盒」横竖各自拉伸铺满绘图区**，所以 `layout:'none'` 的 `x/y`
  只表示「第几列、第几行」这种序号，写成画布像素是没用的；标签留白靠 series 的
  `left/right: 46 / top: 34 / bottom: 44`（标签画在圆下方、比圆宽得多，不留白最左列的字会被切），
  行距则由容器高度决定：`layeredPositions()` 按最大列的行数把容器撑到 `max(560, 行数*56+150)`，
  每行才有 56px 写标签；单层的路径反过来把画布收矮（`max(260, 列数*88)`），
  否则那一点纵向落差被拉满整屏高，会变成一条陡得没法看的斜线。
- **同一个 chart 实例会沿用上一帧的取景变换**：筛身份（3 个节点）再切回「全部」（27 个节点）时，
  新数据被旧缩放顶到画布外 1600 多像素，而且把同一个 option 重放多少次都纠不回来——
  必须 `chart.clear()` 再 `setOption()`。另外包围盒有一根轴跨度为 0（每列只有一个节点时所有 y 相同）
  会把那一向的缩放算成无穷大并污染下一帧，所以单行图按列号给了 0.34 的纵向错开。
  分层视图也因此关掉拖拽（行列号就是语义，拖一下这套坐标就废了），只在力导向里可拖。
  分层列号有两个来源：全图用「最长前置链深度」（后端 `layer` 字段，保证前置边一定从左列指右列），
  选了身份则改用「离目标的 hop 倒序」，同一条学习主线自然从左到右排开。


---

## 七点七、学习清单与 AI 规划（`study_list` 表 + `/study/*`）

图谱页点节点 → 详情卡「加入我的学习清单」→「✨ AI 生成学习规划」，整条链路是：
清单（MySQL `study_list`，唯一键 `(nickname,node_name)`）→ 沿前置边回溯补齐依赖 →
Kahn 拓扑排序 → 按节点类型排周（课程 2 周 / 技能 1 周 / 竞赛 3 周）→ 大模型逐条写理由。

- **AI 只写字、不改顺序**：`app/ai.py` 的 `PROMPT_STUDY_PLAN` 禁止模型改排期或新增节点，
  只准输出 `reasons`（每个节点一句为什么）和 `advice`；理由里一个节点名都没对上就整段退回本地规则版。
- **补齐项也能标学完**：`POST /study/status` 写成 upsert（`INSERT ... AS new ON DUPLICATE KEY UPDATE`），
  因为 AI 补出来的「C语言」原本不在清单里，只给按钮不给它写行，点了必 404。
- **缓存**：`plan:{昵称}` 存 10 分钟；`/study/toggle`、`/study/status` 每次都删它，
  所以点完「学完」计划立刻往后收一格，不会读到旧排期。
- **学完的不占排期**，但仍留在拓扑序里当前置；清单中被改名/删掉的节点走 `orphans` 如实标出来，不静默丢。
- **聚焦态**：点节点后 `visibleNodes()` 只留它和一跳邻居（再点一次复原、切身份也清掉），
  描边就是第二层信息——金边在清单、绿边已学完，聚焦的那个用深蓝粗边。
- 演示库已给 `计科2301张同学`（C语言已学完 / 数据结构在学 / 蓝桥杯待学）和
  `示例·李四`（Java基础 / 实习）灌好清单，`sql/init_tables.sql` 末尾有同样的 `INSERT IGNORE`。

验证脚本（跑完自己把测试痕迹清干净）：

```bash
python tools_study_check.py     # 建档→增删→规划→缓存失效→标进度→图谱标注→空清单→清理
```

---

## 七点八、安全雷达的「有理有据」：条款库 + 四跳链路（`handbook_articles` + `/safety/*`）

雷达不再只给「高危 + 一堆特征」，每次扫描固定跑四跳，页面上逐跳摊开：

```
第1跳 实体富化   抠事实（收费名目/金额/收款方式/证件/验证码/链接/时限施压/账号出借…）
第2跳 风险判定   大模型或本地规则 → 等级、分数、编号证据 E1..En
第3跳 条款检索   app/handbook.py 按「场景 + 关键词 + 风险类型」查 handbook_articles → C1..Cn
第4跳 链路解释   大模型只把「这条条款为什么适用」说成人话，编号由代码给定
```

**判级和依据全由代码算，模型只写字**。四条硬规矩写在 `app/handbook.py` 顶部注释里，
`tools_radar_check.py` 逐条守着：

1. 只有 `verified=1 且 enabled=1` 的条款才可能被引用；
2. 每条引用都要有能一眼复核的理由——原文命中词（`命中词：押金、保证金`）或风险类型对得上，
   两者都没有的条款直接淘汰（早期版本靠分数阈值兜底，结果「可信度高但一个字没命中」的条款也会混进来）；
3. 对不上条款的风险如实进 `missing_basis`，链路写「条款库里还没有对得上的条款」，
   **置信度不给分**（`confidence.value = null`），等级照常判——unknown ≠ safe；
4. 第 4 跳文本里出现引用清单之外的条款号即判 FAIL（模型自己编的条款号一律丢弃）。

- **置信度是算出来的**：`0.5×最强命中强度 + 0.2×佐证条款条数 + 0.3×条款平均可信度`，
  三项都在页面上写成人话（「最强一条依据命中强度 79.8」「可互相印证的依据 2 条」），不让模型自评。
- **条款库现状**：34 条 / 可引用 31 条（国家法律 24、部委文件 7、两高司法文件 1、校方手册 2），
  每条都带 `url` 可回原文核对。故意锁着的 3 条（`--stats` 会列出来）是**没逐字核上官方原文**的，
  例如《学生手册》里只找到转载版的那条——「宁可少一条，不可错一条」。
- **两个引号陷阱**（条款库里已经用 `note` 记下，别再踩）：
  ① 网络安全法 2025 修正后条文整体顺延，旧「第二十七条」现在是**第二十九条**，
  网上大量资料还写着旧号；② 「职业中介不得扣押证件」这类话出自**就业促进法第四十一条**，
  不是常被误引的《人力资源市场暂行条例》。
- **导入口**（本校《学生手册》就靠它进来）：

```bash
python tools_handbook_import.py                      # 导 sql/handbook_articles.json（幂等 upsert）
python tools_handbook_import.py --file 我的学生手册.json   # 学校条款：verified/enabled 先给 0
python tools_handbook_import.py --stats              # 几条可引用、哪几条被锁、为什么被锁
python tools_handbook_import.py --export out.json    # 导出来改完再导回去
```

  导入脚本每次都会删 Redis 的 `handbook:clauses`（雷达全量匹配走这个 10 分钟缓存），
  不然改完条款判词还是旧的。
- **接口**：`GET /safety/handbook?scene=&source=&q=` 给雷达页底部那张「条款库」表用，
  `stats` 里刻意分开「库里有几条」和「能引用几条」，被锁的行灰显但仍列出来（透明比藏起来好）。
- **台账**：`risk_logs` 新增 `cited_articles`（文件+条款号，可回溯到条款库）与 `skill`（扫描时选的检测技能），
  每次扫描把这次的引用一并落库。本机已 `ALTER TABLE` 补上，`sql/init_tables.sql` 同步。
- **检测技能（2026-10-26 新增）**：雷达不只有「自动判」，还能选技能扫——
  `GET /safety/skills` 从条款库 `risk_type` 标签实时聚类出技能清单（押金证件/验证码钓鱼/刷单返利/两卡出借…共 13 项，
  每项自带依据池大小、核心条款数、出处文件与关键词）；`POST /safety/scan` 带 `skill` 参数后，
  第 3 跳只在**该技能的依据池**（带标签条款 + 同场景通用背景条款）里检索，场景也锁成技能的场景——
  引用必有出处，不会串池。条款库增删后技能列表自动跟着变；台账记录技能名，页面上技能 chips 选中即显示依据说明。
- **两条新命中的诈骗特征**（`FRAUD_RULES`）：`出租出借银行卡/账号`（帮信罪，配反电诈法第三十一条
  + 校规第五十二条「可以开除学籍」两条依据成对引用）、`通知里的可疑代收费用`（资料费/班费/扫码缴费，
  只定中危——真实通知也要缴费，靠名目和私人收款渠道区分）。

```bash
python tools_radar_check.py        # 六个用例 + 四条硬规矩，跑完自己删测试台账
python tools_radar_check.py --keep # 想留着看效果就别删
```

---

## 八、常见报错速查表

| 报错信息 | 原因与解法 |
|---|---|
| `'python' 不是内部或外部命令` | 装 Python 时没勾 `Add to PATH`，重装勾上 |
| `'mysql' 不是内部或外部命令` | 用方式 B（Workbench）建表，或手动把 MySQL 的 bin 目录加入 PATH |
| `Access denied for user 'root'` | `.env` 里 `MYSQL_PASSWORD` 和你设的 root 密码不一致 |
| `Can't connect to MySQL server (2003)` | MySQL 服务没运行：`Win+R` → `services.msc` → 启动 `MySQL80` |
| redis 显示 `failed: Connection refused` | `redis-server.exe` 黑窗口没开（Windows），或没执行 `mysql.server start`（Mac 装错命令？Redis 用 `brew services start redis`） |
| `ModuleNotFoundError: No module named 'dotenv'` | 忘了激活 venv（没看到 `(venv)` 前缀），或没执行 pip install |
| pip 下载慢/超时 | 加华为云镜像参数（见第四节命令） |
| `redis: failed: unknown command 'HELLO'` | Windows 版 Redis 是 3.0 老版本，代码里已用 `protocol=2` 强制 RESP2 握手解决 |
| ECharts 图不出来、控制台报 `ERR_CONNECTION_RESET` | CDN 被墙。已把 `echarts.min.js` 下载到 `web/` 本地引用，无需联网 |

---

## 八点半、本机（Windows）实际环境备忘

> 2026-10-25 已在本机装好并全链路验证通过，记录实际参数，重启电脑后照这里拉起服务。

| 组件 | 实际情况 |
|---|---|
| Python | 3.14，项目虚拟环境 `venv/`（`venv\Scripts\activate` 激活） |
| MySQL | 8.4.9，winget 装在 `C:\Program Files\MySQL\MySQL Server 8.4`；**未注册 Windows 服务**，配置和数据目录在 `C:\Users\kkk97\mysql-campus\`（避开管理员权限）；root 密码见 `.env` |
| Redis | Windows 版 3.0（`C:\Program Files\Redis`），已注册为服务 `Redis`，开机自启，无需手动管 |
| 后端端口 | 本机 8000 被微信机器人占用，开发用 **8100** |

**重启电脑后的两条启动命令**（各开一个终端窗口）：

```bash
# 1. 拉起 MySQL（保持窗口开着）
"/c/Program Files/MySQL/MySQL Server 8.4/bin/mysqld.exe" --defaults-file="C:\\users\\kkk97\\mysql-campus\\my.ini" --console

# 2. 启动后端
cd /d/TrueDownload/campus-master/campus-master
venv/Scripts/python -m uvicorn app.main:app --reload --port 8100
```

> 建表只在首次执行，且必须带 `--default-character-set=utf8mb4`，否则中文插入报 1366。

---

## 九、以后切回华为云（比赛提交时）

开通华为云 RDS 和 DCS Redis 后，只需改 `.env` 里这三行，代码零改动：

```
MYSQL_HOST     = <RDS 控制台-连接信息-地址>
REDIS_HOST     = <DCS 实例-连接地址>
REDIS_PASSWORD = <DCS 实例密码>
```

并在 RDS 上重新执行一遍 `sql/init_tables.sql`（用华为云控制台的 DAS 登录窗口粘贴执行）。

> 这就是"配置与代码分离"的价值——评委问起来，这是架构亮点，不是偷懒。
