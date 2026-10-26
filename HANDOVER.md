# 交接文档（AI → AI）

> 本文档是「掌控校园」项目的链路权威。每个会话开工前先通读；收工前必须更新「当前状态」「最近改动」「已知坑」三节。
> 项目根目录：`D:\TrueDownload\campus-master\campus-master`

---

## 一、项目是什么

华为云赛题1「校园信息一体化平台」：FastAPI + MySQL 8.4 + Redis + MaaS 大模型（OpenAI 兼容），前端是纯 HTML+ECharts 静态页（无框架无构建）。三大赛题模块全部完成，另有四条延伸线（官方通知源聚合、学习清单+AI 排期、安全雷达多跳链路、论坛社交化发帖）。

页面（顶栏五入口）：
| 页面 | 职责 |
|---|---|
| `/` | 落地页（web/index.html，后端根路由直出）：一句话故事 + 三模块一句话卡 + 华为云服务映射 + 技术栈跑马灯 + MySQL/Redis 实时状态灯；演示动线与 AI 降级说明在 LOCAL_SETUP.md 七点五 |
| `/web/notice.html` | 情报官：官方源聚合为主信源（可溯源），手动贴入兜底 |
| `/web/kg_demo.html` | 知识图谱：搜索概念织知识网格（中心+双环）、点节点换中心、加入清单、?focus= 直达 |
| `/web/forum.html` | 经验论坛：markdown-lite 编辑器+配图上传，点赞满 30 自动进精华 |
| `/web/safety.html` | 安全雷达：可选检测技能（条款库提炼）、鉴诈四跳链路（结论→证据→条款→置信度）+ 条款库浏览 |
| `/web/profile.html` | 个人中心：昵称唯一档案（学校/身份/年级…），驱动全站 |

---

## 二、怎么跑起来

1. **MySQL 手动起**（未注册服务，重启电脑后要拉）：
   `mysqld --defaults-file=C:\users\kkk97\mysql-campus\my.ini --console`
   库名 `campus_master`，root 密码在项目 `.env`（**不许写进命令行、不许提交、不许贴出来**；用 `venv/Scripts/python.exe` + pymysql + dotenv 操作库，`mysql.exe -e` 会报 1045）。
2. **Redis**：Windows 3.0 老版，已开机自启；redis-py 必须 `protocol=2`（代码已处理）。
3. **后端**：`cd D:\TrueDownload\campus-master\campus-master && venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8100`
   端口固定 **8100**（8000 被微信 AI 机器人占用）。健康检查 `curl http://127.0.0.1:8100/health`。
4. 建表：`sql/init_tables.sql`（**必须 utf8mb4**）；条款库灌数：`python tools_handbook_import.py`；图谱示例数据：`tools_seed_mock.py`（`--clean` 级联删）。

### 重启规则（最容易踩的坑）
**改了 `app/*.py` 必须手动杀掉 8100 进程再重启**——这台机器上 uvicorn `--reload` 监听不到 D 盘文件变化，不重启就一直在跑旧代码。标准操作：
```bash
PID=$(netstat -ano | grep ":8100 " | grep LISTENING | head -1 | awk '{print $5}') && taskkill //PID $PID //F
sleep 2; (PYTHONIOENCODING=utf-8 nohup venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8100 >> uvicorn.log 2>&1 &)
sleep 7; curl -s http://127.0.0.1:8100/health
```
前端 HTML 改完即可生效，但**浏览器验证要带 cache-bust**（如 `?cb=x1`）——Edge/浏览器会用磁盘缓存旧页面，不换参数会看到旧代码假装「改了没用」。

### 测试纪律
- 测试/演示数据必须**一眼是假的**（`测试·`、`示例·` 前缀），用完当场删除并回报（DB 行 + uploads 文件一起清）。
- 不擅自改系统状态（注册表/服务/驱动）；Git Bash 里给 curl 传中文参数会变 `?`，用 `venv/Scripts/python.exe` + httpx 测带中文的接口。

---

## 三、硬约束（动代码前必看）

1. **赛题表 `notices / posts / kg_nodes / kg_edges` 的字段不能改**。所有扩展进自建表：
   `user_profiles`（含 `school` 列）、`risk_logs`（含 `cited_articles`、`skill` 列）、`handbook_articles`、`study_list`、`notice_sources`、`post_media`。官方与手动通知靠 `notices.source_url LIKE 'http%'` 区分，不加列。
2. `.env` 里有 `MYSQL_PASSWORD`，gitignore 之外**任何输出/提交/日志里都不能出现**。
3. `.env` 没配 `MAAS_API_KEY` 时全链路走 `app/ai.py` 本地规则降级（页面会显示引擎标签）；拿到 Key 填进去即切 LLM，**代码不用改**。Prompt 填参一律 `.replace()` 不用 `.format()`（Prompt 里有 JSON 花括号示例）。
4. 安全雷达的证据纪律（改 `handbook.py`/雷达接口时不能破坏）：判级和置信度由代码算、检索决定引用、LLM 只把话说成人话且只能引用喂给它的条款编号（C1/C2…），条款库里没有就明说弃权，绝不编造条款号。
5. 上传图片白名单 jpg/png/webp/gif + **魔数校验**（不信客户端后缀），≤5MB，随机文件名落 `uploads/`；`POST /posts` 只收 `/uploads/` 开头的 URL（防外链注入），最多 9 张。
6. 前端渲染外部内容（官方通知标题、帖子正文）必须先 `esc()` 再打标记（`mdLite` 是 escape-first，`>` 转义后是 `&gt; ` 占 5 字符，切片长度别改错）。`esc()` 必须连引号一起转义（`&quot;`/`&#39;`）——输出经常落进 `title=`/`data-x=`/`onclick=` 属性里；五页的 esc 已统一为引号安全版，新增页面照抄这份正则。

---

## 四、代码地图

```
app/main.py          全部接口：根路径落地页、健康检查/缓存、通知（latest/sources/fetch/official/ai/summarize/briefing）、
                     上传 /upload、帖子（posts/latest/like）、图谱、路径 path:{role}、清单/规划 plan:{nick}、
                     雷达 skills/scan/logs/handbook（scan 可带 skill 锁依据池）、资料 /profile；
                     官方源定时抓取守护线程（run_official_fetch 与手动按钮共用，FETCH_INTERVAL_MINUTES 可配）
Dockerfile/.dockerignore/docker-compose.yml/DEPLOY.md   切云部署物料：镜像构建 + 本地全栈 compose + 华为云部署手册
app/ai.py            所有 LLM 调用+降级：extract_notice / extract_triples / analyze_job_chat / analyze_fraud /
                     chain_explain（雷达连接语）/ plan_study（排期理由）/ summarize_official（官方通知一句话）/
                     brief_intro（简报整合导语）
app/handbook.py      雷达证据层：实体富化 + 条款检索 match_clauses + 置信度 + C 编号
app/official_sources.py  通用官方源抓取：parse_list（正则解析列表页，不引 BeautifulSoup）/
                     fetch_page（httpx verify=False 15s 浏览器 UA）/ extract_detail_text（正文提取+噪音过滤）
sql/init_tables.sql  10 张表 DDL + 演示数据（含 3 条杭电 notice_sources；risk_logs 含 skill 列）
web/*.html           落地页 + 五页 + common.css + common.js；ECharts 已本地化（jsdelivr 被墙）；六页顶栏品牌字回到 /，favicon 为内联 SVG 朱砂印章；
                     全站新中式编辑风（--bg #F6F3EA 暖纸令牌制 + 朱砂/赭金/黛青 + 墨色方角主按钮 + 衬线标题 + 印章/菱形/朱笔圈阅记号）；common.css 带美学层
                     （eyebrow、跑马灯、mono 数字、楷体品牌字/页副标题/空状态）
uploads/             论坛配图（/uploads 静态挂载）
tools_api_check.py / tools_study_check.py / tools_radar_check.py   回归自检（测完自清理）
tools_handbook_import.py / tools_seed_mock.py
```

缓存键（Redis，TTL 600~1800）：`home:latest_notices`、`path:{role}`、`profile:{昵称}`、`plan:{昵称}`、`handbook:clauses`、`briefing:{昵称}`（无昵称时 `briefing:_`）。
失效规则：发帖/改档案/官方抓取新通知 → 对应 delete（改档案同时删 briefing）；`/debug/drop-cache` 全清（演示用）。

关键设计取舍：
- **官方源是主信源，手动贴入兜底**：抓取只入库标题+链接（content 空、summary 空），点「AI 一句话」才按需抓详情页生成摘要并写回；详情页抓不出正文时摘要退化成标题（诚实降级，`POST /notices/{id}/summarize` 对手动贴入返回 400）。
- **加学校/加源 = INSERT 一行** notice_sources（school+dept 唯一），前端学校选择器读个人中心 `cm_school`，无默认硬编码（页面默认值仅是示例）。
- **论坛配图**：`post_media(post_id, url, sort)`，列表接口批量查回拼进 `images` 字段。
- **学习路径**：图谱前置边反向回溯 ROLE_ANCHORS 拓扑排序，LLM 只写理由不改顺序。
- **雷达技能不是写死清单**：`GET /safety/skills` 从条款库 risk_type 标签实时聚类（`_derive_skills`），每项技能自带依据池（带标签条款 + 同场景通用背景条款）；`POST /safety/scan` 带 `skill` 即锁定该池并锁定场景，第三跳只在池内检索——引用必有出处。条款库增删技能列表自动跟着变，不存在的技能返回 400。
- **知识网格（图谱唯一视图）**：搜索/点节点即以该概念为中心织网——内圈直接邻居 ≤8、两跳模式外圈 ≤12（`gridScope`），坐标为「中心原点 + 双椭圆环」（`gridLayout`）。包围盒经各向异性映射锁成绘图区比例、铺到 84%，`series.zoom = W/plotW` 抵消铺满，净缩放恒为 1——任何节点数（含 2 节点/1 关系退化情形）不变形不放大。series 矩形（left:80/right:80/top:50/bottom:70）必须与 gridLayout 的留白假设一致。
- **情报官个性化简报纪律**：`GET /notices/briefing` 的相关度打分/筛选全部由代码算（身份关键词 ×18 + 本校官方源 +12 + 新近度，命中词随响应返回可回溯）；AI 只把入选通知整合成导语、只能提喂给它的标题（同雷达纪律）；标题里出现的图谱概念带出 `kg_demo.html?focus=概念` 织网入口，通知↔图谱两条线缝在一起。
- **手写记号体系（2026-10-26 第十轮起，用户认可「符合学生的网站」）**：`[data-ring]` 元素由 `web/common.js` 注入朱笔圈 SVG（首页标题静态写死不用 JS）；动画 `ringDraw` 五停靠 dashoffset（落笔慢→行笔快→收笔慢→尾巴搭上），时长/延迟用 `--ring-dur/--ring-delay` 变量调（首页 1.9s/.35s，子页默认 1.4s/.15s）；首页印章 `sealStamp` 延迟 2.1s 跟在圈后。`.page-sub`/`.empty` 走楷体（--font-kai）出手写感；给标题加圈 = 挂 `data-ring` 一个属性即可。
- **全站新中式编辑风（2026-10-26 第七轮起）**：亮色令牌制（--bg #F6F3EA 暖纸 / --card #FCFBF6 / 朱砂 --primary #B0432E 文字档 + --primary-bright #C25437 填充档 / 赭金 --gold #A87B2F / 黛青 --info #33586B / 墨 --ink #211F1A）；主按钮/激活态一律墨色方角 10px（`var(--ink)`），别再用 primary 当按钮底；标题走 `--font-display` 衬线；独有记号=印章（.brand-mark/.hero-seal 内嵌奶油描边）、菱形标记（card-title/mod-list rotate 45deg）、压印硬阴影（4px 4px 0，hover 朱砂抬升）。第六轮的 Anthropic 米白暖色（陶土橙 #C15F3C/#D97757）已整体作废，别再参照——那套色板正是 Anthropic 品牌色，用户点名「容易被一眼看出模仿」。第五轮的暗色系同样作废。

---

## 五、当前状态（截至 2026-10-26）

- 三大赛题模块 + 四条延伸线全部实现并**端到端验证**：后端 curl/httpx 实测 + 浏览器 MCP 实测（带 cache-bust）。
- 官方源已录入 3 个杭电源并实测：学校通知公告（www/tzgg）、教务处（jwc 栏目 13022）、就业指导中心（job 首页静态区）；单次抓取 29 条、二次抓取 0 条（去重生效）。
- 论坛发帖升级实测：上传→魔数拒绝假图→发帖带图→列表带 images→配图/缩略图/预览/markdown 渲染全通过；测试帖已清理。
- 回归工具全绿：`tools_radar_check.py`（6 案例断言）、`tools_api_check.py`、`tools_study_check.py`。
- 2026-10-26 bugfix+动效轮完成：五页浏览器逐页验收（console 全净、图谱/清单/条款库/资料回读全通）。
- 2026-10-26 评委视角轮完成：落地页上线（GET / 直出 index.html）；缓存命中可视化（4 接口带 cache={hit,key,ms}，徽章显示「Redis 缓存命中 · 0.6ms / 查 MySQL 并回填缓存 · 31.4ms」）；drop-cache 扩到 profile:*/plan:*/handbook:clauses（scan_iter 按前缀扫）；实测回源→命中约 50 倍耗时差。
- 2026-10-26 图谱稳定性轮完成：分层视图重写为设计像素+等比包围盒+zoom 抵消铺满（净缩放实测恒 [1,1]，27 节点全图/3 节点路径/聚焦一跳全部无变形）；力导向参数按节点数分三档 + friction 0.18 + 延迟回位 2.6s（实测 3 节点 1.2s 内静止）；plot 尺寸改用 chart.getWidth/Height + 无条件 resize（隐藏页签 inline style 不落布局）。
- 2026-10-26 第五轮（暗色 + 网格 + 简报）完成，浏览器逐页验收（body rgb(10,16,31)、console 全净）：全站暗色系；图谱推倒重建为搜索中心知识网格（React框架 2 节点退化情形实测 netScale [1,1]）；情报官简报链路 httpx + 浏览器实测（竞赛档案 → 竞赛通知霸榜 + 命中词 + kg 织网跳转，二次调用缓存命中 13.8ms，drop-cache 覆盖 briefing:*）；回归三件套全绿自清理。
- 2026-10-26 第六轮（Anthropic 风格）完成，六页浏览器逐页验收（body rgb(240,238,230)、console 全净、kg 网格 netScale 仍 [1,1]）。
- 2026-10-26 第七轮（新中式编辑风）完成，六页浏览器逐页验收（body rgb(246,243,234)、console 全净、kg 网格 zoom 0.84 中心朱砂描边+赭金包含边、简报 6 条+织网链接 2 条、接口冒烟 4 个全绿缓存命中）。
- 2026-10-26 第八轮（定时抓取 + 部署物料）完成：抓取调度 1 分钟间隔实测两轮（首轮 +1 条真实新通知、次轮 +0 去重生效）后恢复默认 30 分钟；回归三件套全绿自清理；compose config 语法验证通过，docker build 因本机 Docker Desktop 守护进程未启动未跑成（补验步骤见已知坑）。
- 2026-10-26 第九轮（首页圈阅动画）完成：落地页标题「朱笔画圈 + 盖印」动画，CSSOM 关键帧 + getAnimations/finish() 终态逐项验证（dashoffset 0 / 印章 rotate 3deg opacity 1），console 全净。
- 2026-10-26 第十轮（手写风格推广）完成：首页圈改手写节奏、五页标题 JS 注入圈阅、楷体点缀，六页逐页验（注入/动画/楷体全中、console 全净）。
- 2026-10-26 第十一轮（黑椭圆惨案 + 版本化子资源）完成：定性=用户端旧 common.css 缓存撞新 HTML（SVG 无样式黑填充糊满 hero）；六页子资源链接全部带 `?v=10`，新 CSS/JS 验证加载正常（fill none / 暖纸底）。
- 2026-10-26 第十二轮（圈阅豁免减少动态 + 补笔 + 手绘下划线）完成：用户端看不到画圈过程，定性=系统「减少动态效果」把全局动画压成瞬时；圈阅豁免该开关（纯描边低动效），主圈后加补笔小尾巴，card-title 加手绘朱砂下划线；六页 v=11，浏览器逐项验证（豁免规则在 kill-switch 之后、尾巴 0.418s 延迟 2.25s、finish() 终态 dashoffset 0、console 全净）。
- 2026-10-26 第十三轮（首页排版 + 纸质感 + 荧光笔）完成：`.grid-eq` 等高排版修三行卡片底边参差（桌面宽度模拟实测 420×3 / 611×2 / 561×2 全等，按钮压卡底）；`.card` 铺 feTurbulence 纤维噪点（opacity .05）出纸质感；小红书荧光笔 `.mk`（黄/绿/粉三色手绘边缘 SVG，避开 hero 的 .hl 渐变字类名），首页 hero 三连 + AI 卡「代码零改动」+ 五页 page-sub 各一处；六页 v=12，console 全净。
- 2026-10-26 第十四轮（tooltip 溢出 + 发帖弹窗产品化）完成：kg tooltip 补 `white-space:normal` 实测 300px 内折行；论坛发帖从右栏内嵌卡改为居中弹窗（页头/右栏双入口），代码块带语言标签 + 复制 + **js 可运行**（Web Worker 沙箱，console 捕获 + 3 秒死循环强杀，实测正常输出/报错/超时三路全通），草稿 localStorage 随输入自动保存、重开弹窗恢复、发布成功才清；本轮只改 forum.html/kg_demo.html 内联代码，common.css/common.js 未动 **v 保持 12**；验收草稿已清，console 全净。
- 2026-10-26 GitHub 托管 + Pages 上线：**公开仓库 https://github.com/KKK9747human/campus-master**（先私密后按用户要求转公开；.gitignore 护住 .env/venv/日志/uploads/_archive，提交前索引密钥扫描通过、.env 未跟踪）。**线上地址 https://kkk9747human.github.io/campus-master/**——gh-pages 分支 = web/ 静态镜像，由 `bash tools_deploy_pages.sh` 维护（copy + 三条 sed：/web/→相对、品牌 logo href=/→index.html、撤 /docs 入口；**改完 web/ 跑一次即可**，Pages 构建约 1 分钟）。common.js 带 Pages 探测：仅 *.github.io 域名在页底出「Static demo」提示条（后端不在线，接口 404 属预期），本地/云上不受影响。v=14（第十五轮起）。

## 六、最近改动（倒序）

- 2026-10-26（第十五轮）首页精简 + 跑马灯真滚动 + 动画借鉴 doubao-samurai-opt（用户：① 首页字太多，删掉「给评委看」等非正式语句，说明性文字进项目文档 ② 跑马灯做成滚动循环，动画参考 E:\code\doubao-samurai-opt）：
  - **index.html 推倒重写（232 行 → 150 行）**：删掉「给评委的演示动线」卡（steps+清缓存按钮）、AI 引擎说明卡、模块卡的长 bullet 列表、hero 长段落——全部下沉：演示动线五步 + 清缓存徽章验法进 `LOCAL_SETUP.md` 七点五（原有的「演示动线建议」段落扩成 ①建档②图谱③发帖④情报官⑤雷达 完整版），AI 降级说明本来就在七点五有。模块卡改一句话 `mod-line`（情报官/图谱/雷达各一句 + 跳转按钮），底排剩 论坛&个人中心 + 华为云服务映射 两卡。`dropCache()`/`#demo-msg` 从首页移除（后端 /debug/drop-cache 保留）。落地页行头描述同步（HANDOVER 一、LOCAL_SETUP 七点五表格）。
  - **跑马灯静止的根因 = kill-switch**：用户机器系统级「减少动态效果」→ common.css 全局把 animation 压成 .01ms×1 次，42s 无限横滚直接变成一排死文字。豁免：在圈阅豁免同块追加 `.marquee-track { animation-duration: 42s !important; animation-iteration-count: infinite !important; }`（匀速横滚是信息带的身份动作）。验收实测 computed 42s/infinite ✓。
  - **借鉴 doubao-samurai-opt 的四拍**：① 滚动揭示 `.reveal`（opacity+translateY，IO threshold .12，同屏按 DOM 序错峰 90ms；**落定 1.2s 后摘掉 reveal/in 类**，否则慢速 transition 会吞掉卡片 hover 的跟手度）；② 印章 `sealFloat` 9s 缓浮（sealStamp 落定后 2.75s 接力，index 内联 reduced-motion 豁免完整顶回）；③ `.card` hover 缓动 .2s ease → .45s cubic-bezier(.22,.61,.36,1)（premium 手感，全站生效）；④ tech-chip 悬浮上浮 2px。
  - **验收环境坑（不是代码 bug）**：browser-use 隐藏浏览器 `document.hidden=true` 且不渲染 → IntersectionObserver 回调永不触发，`.reveal` 全部停在 opacity 0 是预期现象；真浏览器可见即触发（doubao 同款标准做法，没加 failsafe）。
  - **Swagger 按钮 sed 改容错**：按钮文案改短（「接口文档 Swagger ↗」→「接口文档 ↗」），tools_deploy_pages.sh 的撤按钮 sed 从全串匹配改成 `<a class="btn btn-ghost" href="/docs"[^>]*>[^<]*</a>` 正则，以后改文案不用再同步脚本。v=13 → v=14（六页已同步）。

- 2026-10-26（补）公开仓库补 README.md：面向访客的门面（在线 demo 链接 + 功能表 + 快速开始 + 文档索引，静态镜像不在线这点如实写明）；README 不进 gh-pages 镜像（部署脚本只拷 web/）。

- 2026-10-26（GitHub 托管 + Pages 上线）公开仓库 + 静态镜像部署（用户：公开吧，并且部署）：
  - **转公开 + Pages**：免费计划私密仓库开不了 Pages（422），转公开后 `gh api .../pages -X POST` 选 gh-pages /(root) 一次成功；线上 https://kkk9747human.github.io/campus-master/ 实测首页/子页/相对路径/提示条全通，console 仅预期中的接口 404。
  - **Pages 镜像的两个坑**（tools_deploy_pages.sh 内已固化）：① Pages 是项目子路径 `/campus-master/`，页面里 `/web/...` 绝对路径（导航/css/js）和品牌 logo `href="/"` 全会跳到 github.io 根 404——镜像里 sed 改相对路径；② `/docs`（Swagger）后端产物不存在——首页该按钮在镜像里移除。
  - **静态演示提示条**：common.js 探测 `location.hostname` 是否 *.github.io，是则页底挂墨色提示条「后端接口不在线，仅可浏览界面」；本地/云部署不受影响。index.html 因此补了 common.js 引用，v=12 → v=13（六页已同步）。
  - **部署流程**：以后改完 web/ → `bash tools_deploy_pages.sh` 一条命令（worktree + sed + 提交推 gh-pages），main 照常手动 commit/push。

- 2026-10-26（第十四轮）tooltip 溢出 + 发帖弹窗（用户：①如图字超出边框 ②发帖弹新窗口+代码格式+可运行+随时保存 ③按产品设计）：
  - **tooltip 溢出**：ECharts tooltip 容器默认 `white-space: nowrap`，内层 `max-width` 管不住不断行的中文长句。修复=formatter 里名称行单独 nowrap、描述 div 开 `white-space:normal; max-width:300px; line-height:1.65`。实测：46 字描述折进 300px，scrollWidth==clientWidth，白框 316×81 不再被冲破。
  - **弹窗创作器**：右栏「发布经验帖」卡撤掉，改 `#composer.modal-mask` 居中弹窗（max 760px，backdrop blur，Esc/点遮罩/×关闭，开弹窗锁 body 滚动）；入口两处——页头主按钮「✍ 写经验帖」+ 右栏新增「发一篇帖 = 长一张图」导流卡。编辑器字段/工具条/配图/预览原样搬进弹窗，textarea 加高到 200px，Ctrl+Enter 快速发布。
  - **代码块升级**：mdLite 围栏支持 ```` ```lang ```` 记语言（data-lang）；`enhanceCodeBlocks()` 给每个 pre 加工具条——语言标签 + 复制 + **▶ 运行（仅 js）**。运行=Web Worker 沙箱（Blob URL，console 四法重定向 postMessage 回传，try/catch 兜错误，**3 秒超时 terminate 防死循环**）；输出 `.code-out` 追加在代码块下方，再点运行会终止上一个 Worker。预览和帖子列表都走 enhance。
  - **草稿自动保存**：`cm_post_draft`（title/content/author/at），输入防抖 400ms + 关弹窗即存；重开弹窗自动恢复并提示「已恢复 HH:MM 的草稿（配图需重新添加）」；**发布成功才清**。验收用的草稿已当场清掉。
  - **v 未动**：本轮没碰 common.css/common.js，六页保持 v=12（版本号只跟着这两个文件走）。

- 2026-10-26（第十三轮）首页卡片排版 + 纸质感 + 荧光笔划重点（用户：①注意首页卡片排版 ②某些卡片加纸质质感 ③重点模仿小红书用荧光笔画起来）：
  - **等高排版**：`.grid` 原是 `align-items: start`，一行卡片底边随内容长短参差。新增 `.grid-eq`（stretch + 卡片转 flex 纵列），首页三个网格挂上；`mod-link`/末位 `btn-row` 用 `margin-top:auto` 压到卡底（带 padding 保最小间距）。**验证坑**：隐藏浏览器视口只有 724px，960px 断点把网格压成单列，等高看不出来——临时把列数改回 2/3 栏量完再还原。
  - **纸质感**：`.card` 底色上叠一层 180×180 feTurbulence 灰度噪点（feColorMatrix 去饱和 + opacity .05），全站卡片 + hero 都是纸面纤维手感，性能无感。
  - **荧光笔 `.mk`**：手绘不规则边缘 SVG（viewBox 120×26 blob）当背景，默认荧光黄 #FFD84D，`.mk-green`/`.mk-pink` 两色变体；`box-decoration-break: clone` 保换行不断笔。**类名必须避开 `.hl`**——hero h1 的「校园」渐变字占用中。划重点位置：首页 hero 该知道/该学/该防三连（黄/绿/粉）、AI 卡「代码零改动」、五页 page-sub 各一处。
  - **v=11 → v=12**：六页 sed 一把过。

- 2026-10-26（第十二轮）圈要有动画过程 + 标题手绘下划线（用户：圈要模拟手画出来的过程，要有动画。一些标题也可以加手绘风下划线）：
  - **动画被压成瞬时**：用户机器开了系统级「减少动态效果」→ common.css 末尾的全局 kill-switch（`.01ms !important`）把圈阅也压没了，圈直接是画完的样子。**豁免**：在 kill-switch 之后追加高优先级 `@media (prefers-reduced-motion: reduce)` 块，`.title-ring path`/`.tail` 恢复正常时长——圈阅是纯描边、无位移缩放的低动效装饰，保留安全。
  - **补笔尾巴**：主圈闭合后再描一小段（`M 96 10 C 70 12, 48 17, 28 27`，透明度 .6），像真人收笔的手感；时长/延迟用 `calc(var(--ring-dur) * .22)` / `calc(var(--ring-delay) + var(--ring-dur))` 跟随主圈变量，首页 0.418s 延迟 2.25s、子页 0.308s 自动对齐。index.html 内联 SVG 和 common.js 注入路径都加了 `.tail`。
  - **card-title 手绘下划线**：data-URI SVG 波动扫线（朱砂、透明度 .45）铺在卡片标题底部，`width: fit-content` 让线只随文字宽度；实测首页/情报官页均已生效。
  - **v=10 → v=11**：六页 sed 一把过（index 无 common.js 引用属正常）。

- 2026-10-26（第十一轮）修「一大坨黑椭圆」+ 子资源版本化：
  - **定性**：用户截图里的大黑椭圆 = 浏览器缓存了第 10 轮之前的 common.css，而 index.html 是新的（圈 SVG 在 HTML 里）——SVG 找不到任何样式规则，按 SVG 默认行为黑填充 + 占位在文档流里，糊满 hero。强刷（ignoreCache）后 fill:none/209×87 绝对定位全部正常，代码本身无 bug。
  - **根治**：六页 `<link common.css>` / `<script common.js>` 全部加 `?v=10`（首页绝对路径 /web/，子页相对路径两种形态都处理）。以后改这两个文件 → 六页 v 号 +1，子资源缓存自动失效，评委/访客无需强刷。

- 2026-10-26（第十轮）手写风格推广（用户：①画圈太快要有手写过程 ②思路好，多用手写风格优化其它页面）：
  - **首页慢圈**：`ringDraw` 从单停靠改五停靠关键帧（100→64→22→4→0，等分时长不等分笔画：起笔缓、中段快、收笔拖、尾搭上），时长 0.85s→1.9s，起笔 0.5s→0.35s；印章延迟 1.2s→2.1s 对齐圈闭合。
  - **五页圈阅**：圈样式从 index 内联抽到 common.css（`--ring-dur/--ring-delay` 变量化）；新增 `web/common.js`——`[data-ring]` 元素自动注入朱笔圈 SVG，五页 page-head h1 挂 `data-ring` + 引入脚本（defer）。
  - **楷体点缀**：`.page-sub`（页副标题）与 `.empty`（空状态）改 --font-kai，叙述性文字出手写感；技术性 hint/徽章保持 mono 不动。

- 2026-10-26（第九轮）首页「圈阅」掌控感动画（用户点名：画圈圈起标题=完美圆满）：
  - **叙事**：中式批阅动作——朱笔绕标题手绘一圈（圈阅=选定、圆满），0.5s 起笔 0.85s 画完；圈落定后 1.2s 右上角「掌控校园」印章以 stamp 弹性缓动砸下（rotate 9°→3° + scale 1.7→1）。「圈阅 → 落印」两拍完成掌控感。
  - **实现**：h1 内 `.ringed` 包裹中文标题，叠 SVG 椭圆（手绘感贝塞尔闭合路径 + 尾部搭在起笔上）；`pathLength=100` + dasharray/dashoffset 100→0 描边动画；`vector-effect: non-scaling-stroke` 保证 preserveAspectRatio=none 拉伸下笔迹粗细一致；`prefers-reduced-motion` 由 common.css 全局 kill-switch 兜底（终态直出，不会出现「圈永远不闭合」的破相）。
  - **验收坑复认**：隐藏页签动画时钟不推进（getAnimations 全员 currentTime=0），computed style 卡在 from 态——这是测量假象；用 CSSOM 查关键帧定义 + `anim.finish()` 推终态核对。

- 2026-10-26（第八轮）官方源定时抓取 + 切云部署物料：
  - **定时抓取（零新依赖，不引 APScheduler）**：抓取核心抽成 `run_official_fetch()`（手动「拉取最新」与定时共用，校验逻辑不变）；后台守护线程每 `FETCH_INTERVAL_MINUTES` 分钟（.env 配，默认 30，0=关）对 `notice_sources` 里启用官方源的学校各跑一轮，冷启动让路 60s 再跑首轮；单校失败不杀线程，日志前缀 `[fetch-cron]` 进 uvicorn.log。验证方式：启动时环境变量 `FETCH_INTERVAL_MINUTES=1` 覆盖（load_dotenv 不覆盖已有环境变量，不用动 .env），实测首轮抓到教务处当日新公示 1 条、次轮去重 0 条。
  - **部署物料**：`Dockerfile`（python:3.12-slim，.env 不进镜像、uploads 挂卷）、`.dockerignore`（.env/venv/日志/uploads 全挡）、`docker-compose.yml`（本地全栈 app+mysql:8.4+redis:7，init_tables.sql 自动建表，容器内用服务名互访，端口不发布 3306/6379）、`DEPLOY.md`（华为云 RDS/DCS/MaaS/ECS 五步部署 + .env 11 键清单 + 验证清单；与 LOCAL_SETUP.md 分工：裸机跑法在那边，容器跑法在这边）。

- 2026-10-26（第七轮）去 Anthropic 化 → 新中式编辑风（用户反馈「容易被一眼看出模仿 anthropic」「前端不够吸引人」，第六轮整体作废）：
  - **问题定性**：米白 #F0EEE6 + 陶土橙 #D97757 + 炭黑 pill 正是 Anthropic 官方品牌三件套，照抄等于自报家门。
  - **令牌翻转**：common.css 重写——--bg #F6F3EA 暖纸、--card #FCFBF6、朱砂双档（--primary #B0432E 文字 / --primary-bright #C25437 填充）、赭金 --gold #A87B2F、黛青 --info #33586B、墨 --ink #211F1A；语义色换新中式哑档（苔绿/赭金/砖红/黛青）；氛围底换朱砂微光+墨点阵。
  - **独有记号**（区别于 Anthropic 的关键）：.brand-mark 与首页 .hero-seal「掌控校园」2×2 楷体印章（内嵌奶油描边 + 3deg 微旋 + 压印硬阴影）；card-title/mod-list 标记从圆点改菱形（rotate 45deg）；卡片阴影 4px 4px 0 硬压印（hover 朱砂晕+抬升）；按钮从 pill 改 10px 方角 + letter-spacing；page-head 加发丝线；跑马灯分隔改赭金 ◆；h1 提到 42px，「校园」二字朱砂→赭金渐变字（background-clip: text）。
  - **六页硬编码清扫**：kg_demo（INK 常量 + TYPE 三色改苔绿/朱砂/黛青 + 关系线改暖灰/浅灰/赭金 + 中心光晕朱砂 + 图例「金=包含」+ 清单金边 #A87B2F/完成绿边 #3E6B4F）、notice（.kg-link 朱砂描边）、safety/profile/kg 的 #FAF9F5→#FCFBF6、path-num/steps 序号圆改方角 8px；favicon 六页统一换朱砂印章款（内嵌描边 serif「控」）。

- 2026-10-26（第六轮）全站换 Anthropic 米白暖色（用户拍板「模仿 anthropic.com」，第五轮的暗色系整体作废）**【已被第七轮整体作废，仅存档】**：
  - **令牌翻转**：common.css 重写——--bg #F0EEE6 奶油底、--card #FAF9F5、炭黑 #191919、陶土橙双档（--primary #C15F3C 文字档 / --primary-bright #D97757 填充档）；语义色改哑编辑风（鼠尾草绿/琥珀/砖红/石板蓝）；氛围底换暖纸感（陶土微光+极淡点阵，去暗晕）。
  - **Anthropic 语言落地**：主按钮/激活片/顶栏 active 一律炭黑 pill；h1 与卡片标题走 Georgia/宋体衬线（h1 提到 24px）；顶栏半透明 blur；卡片细边框极简（hover 只加深边框不压黑影）；favicon 六页换陶土橙。
  - **六页硬编码清扫**：kg_demo（INK 常量 + TYPE 三色改鼠尾草/陶土/石板蓝 + 关系线暖灰/浅灰/棕 + 中心光晕 + 图例色）、safety（.evi-no/.clause-no 炭黑底）、notice（.src-chip-btn.on 炭黑、.kg-link 陶土）、profile（档案卡改暖炭黑渐变）、index（tech-chip/steps 序号）；顺手给 notice 一直裸奔的 .summary-box/.divider/.hl-item/dl.kv/.src-chip 补了最小样式（暖白嵌板+发丝线）。

- 2026-10-26（第五轮）暗色系 + 知识网格 + 情报官简报：
  - **全站暗色系**：common.css 令牌翻转（--bg #0a101f / --card #111a30 / --text #e6ebf7，语义色换亮档，亮色主元素压 #0a101f 深字，氛围底/发光重调）+ 六页硬编码色逐页清扫（safety .evi-no、notice 芯片、profile 渐变卡、forum 工具条、index 跑马灯章、kg plan 徽章）。
  - **知识图谱推倒重建**：弃分层/力导向/聚焦交互（用户反馈 bug 太多），改为「搜索概念 → 以它为中心织网」：搜索框+datalist 热门概念、内圈 ≤8 外圈 ≤12、点节点换中心、↺ 自动中心、`?focus=` 直达（简报的织网链接用）；kg_demo.html 全量重写（621 行），index.html 演示动线同步改词。
  - **情报官个性化简报**：`GET /notices/briefing?nickname=`（打分代码算可回溯，AI 只写导语——ai.py 新增 `brief_intro`，无 Key 本地模板降级）；简报卡置顶 notice.html（引擎标签 + 缓存耗时徽章 + 相关度/命中词/图谱概念织网链接）；缓存 `briefing:{昵称}` 600s，drop-cache 前缀已扩，改档案即失效。
  - **ECharts 铺满教训升级**：只把包围盒宽高比「算对」不动坐标是无效的——必须对坐标做各向异性映射把内容比例真正锁成绘图区比例；series 矩形要和布局留白假设一致（本次 left/right/top/bottom 从 0 改成 80/80/50/70 才对上）。

- 2026-10-26（第四轮）雷达技能化 + 美学移植：
  - **安全雷达技能化**：`GET /safety/skills` 从条款库 risk_type 标签聚类出 13 项技能（池大小/核心条款数/出处/关键词）；`POST /safety/scan` 新增 `skill` 参数——锁定依据池 + 锁定场景，hop3 摘要注明「技能限定依据池 N 条」，响应带 `skill` 溯源；`risk_logs` 加 `skill` 列（init_tables.sql 已同步），台账命中特征列显示技能徽章；safety.html 加技能 chips（全条款库/技能名·N条）+ 选中技能的依据说明行。非法技能 400。回归 `tools_radar_check.py` 全绿。
  - **美学移植**（参考 `E:\code\doubao-samurai-opt` 与 `E:\code\doubao`，取气质不搬暗色）：common.css 新增 `--font-mono/--font-display/--font-kai` 令牌、body 藏蓝点阵+顶部微光+轻收晕氛围底（全在 4% 上下，不伤表格可读性）、`.eyebrow` 小字距标签、`.marquee` 跑马灯（悬停暂停，尊重 reduced-motion）；stat/E/C/名次等数字读数一律等宽；落地页 hero 改宋体报头 + eyebrow + 技术章跑马灯，七张卡片加眉批；品牌字「控」用楷体。
  - 两者都端到端验证：技能链路 httpx + 浏览器实测（扫描/徽章/hop3/台账/清理），美学用 computed style + 布局尺寸逐项核对（截图面板仍隐藏）。
- 2026-10-26（第三轮）评委视角优化：
  - **落地页**：新增 `web/index.html`（项目故事/三模块卡片/支撑能力/评委五步动线/华为云映射表/AI 降级说明/清缓存演示按钮/健康状态灯），`GET /` 由 JSON 改为 FileResponse 直出（文件缺失时退回 JSON）；FastAPI /docs 可当接口自测页用。
  - **缓存可视化**：`cache_flag()` helper 给 4 个缓存接口（latest/path/profile/plan）响应加 `cache={hit,key,ms}`；notice/profile/kg(路径+计划) 四处徽章显示耗时；落地页加「清空缓存（演示回源）」按钮。
  - **drop-cache 补全**：原来只清 home+path，漏了 profile/plan/handbook——演示时会露馅（清了还命中），现在 scan_iter 按前缀全清。
  - 细节：六页品牌字改为链接回 `/`，全部页面加内联 SVG favicon。- 2026-10-26（第二轮）查改 bug + 优化前端 + 动效：
  - bug：五页 `esc()` 统一为引号安全版（防 `title=`/`data-`/`onclick=` 属性注入）；safety 台账 `r.nickname`、扫描错误 `d.detail`、kg `loadPath` 报错转义；**kg tooltip 的节点描述（来自帖子）转义**；handbook 列表先切原文再 esc（不再切在实体中间）；forum `prefixLine` 先取光标再赋值；`like()` 校验 `res.ok`。
  - 优化：五页补 viewport meta；notice 官方列表 / forum 帖子流 / safety 条款库改 loading-dots 加载点。
  - 动效：common.css 动效层（fadeUp 列表入场 stagger、popBeat 点赞、卡片悬浮抬升、按钮按压回弹、focus-visible 键盘焦点圈），论坛灯箱 lbIn/lbZoom，全部尊重 `prefers-reduced-motion`。
- 2026-10-26（第一轮）：论坛发帖社交化（`POST /upload` 魔数校验、`post_media` 表、编辑器工具条/预览/拖拽粘贴配图/灯箱，`mdLite` escape-first 渲染）；官方通知源聚合上线（notice_sources 表 + 4 个新接口 + notice.html 改版）；profile 加学校字段；`LOCAL_SETUP.md` 补雷达章节。
- 2026-10-25：安全雷达四跳链路 + 条款库（handbook_articles 34/31 条）+ 引用可回溯 + 弃权纪律；risk_logs 加 cited_articles。

## 七、已知坑 / TODO

- **MaaS 未配 Key**：全部 local-rules 降级（演示可用但摘要质量一般）。配 Key 后无需改代码，页面引擎标签自动变化。
- **杭电研究生院（grs）/图书馆（tsg）是 JS 渲染**，通用抓取器读不到，**没有录入** notice_sources；别再踩一遍去试。就业中心详情页部分抓不出正文 → 摘要退化为标题（属诚实降级，不是 bug）。
- 就业中心列表项日期形如 `[03-31]` 无年份 → `publish_date` 为空，列表显示抓取日期；如需更准要加年份推断（未做，避免猜错年份）。
- 官方源**定时抓取已内置**（第八轮）：守护线程随进程启动，每 `FETCH_INTERVAL_MINUTES` 分钟一轮（默认 30，0=关），与手动按钮共用 `run_official_fetch`、去重幂等；**别开 uvicorn 多 worker**——线程随进程走，多 worker 每份各跑一轮（不会重复入库，但白压学校网站）。
- `parse_list` 的内容链接正则（`/page.htm|/view/aid/|/art/\d|/info/|/20\d{2}/...`）覆盖常见高校 CMS，换新学校若抓不到先看是不是列表页 JS 渲染或链接形态不在其中。
- `mysql.exe` 命令行连不上（1045），一律走 pymysql；Git Bash 传中文参数给 curl 会损坏。
- 浏览器 MCP 里 CDP click 偶发不触发 JS（页面无反应），用 `evaluate_script` 里 `element.click()` 复核再下结论。
- Qoder 内置浏览器 `prefers-reduced-motion: reduce` 常开：动效在里面全被 kill-switch 压成 0.01ms（getComputedStyle 显示 `1e-05s`），别误判成 CSS 没写上；验收动效要用 CSSOM 查规则或换真机浏览器。
- **ECharts graph 的 `series.zoom` 是乘在「节点包围盒铺满绘图区」之上的**：布局 'none' 时 ECharts 把节点坐标包围盒独立拉伸 x/y 铺满绘图区——少节点时包围盒小、被吹到巨大，且内容比例 ≠ 绘图区比例时横竖缩放不同必然变形。现行解法见 kg_demo.html `gridLayout()`：对坐标做**各向异性映射**把内容包围盒真正整成绘图区比例（只改 w/h 数值不动坐标是无效的，第一版栽过）+ `zoom = W/plotW` 抵消铺满；series 的 left/right/top/bottom 必须与布局函数的留白假设一致（80/80/50/70），对不上铺满倍率就错。
- **隐藏页签里 inline style 不落 computed style**：Qoder 内置浏览器 visibilityState=hidden 时，JS 改 el.style.height 后 getComputedStyle/rect 仍是旧值（连 background 都不刷）——要用 `chart.getWidth()/getHeight()`（ECharts 自己认的尺寸）当真值并无条件 `chart.resize()`。
- **cache-bust 只救 HTML，救不了子资源**：`?cb=x1` 换了页面 URL，但 common.css/common.js 还是磁盘缓存——轻则「页面新 CSS 旧」的劈叉（eyebrow 有字距没字体），重则第 10 轮的黑椭圆惨案（HTML 里有 SVG、旧 CSS 里没有 .title-ring 规则 → SVG 默认黑填充糊满 hero）。**根治（第 11 轮）**：六页的 `<link>`/`<script>` 引用已带 `?v=14` 版本号——**每次改 common.css/common.js 必须把六页的 v= +1**（sed 一行的事），用户端即自动拿新文件，不靠任何人强刷。验收时浏览器 MCP 侧仍建议 `reload ignoreCache`。
- **部署物料未做镜像级验证**：本机 Docker Desktop 守护进程没启动（`docker build` 连不上 npipe），compose config 语法已过。要补验：启动 Docker Desktop 后 `docker build -t campus-master .`，再 `docker run --rm --env-file .env -p 8199:8100 campus-master` 冒烟（容器内连 127.0.0.1 的 MySQL 会显示未连接，属预期，只验进程能起、/health 有 JSON）。

## 八、会话收工清单

1. 测试数据清干净（DB + uploads），回报清理结果。
2. 重启过几次后端的话，确认 8100 上跑的是最新代码（`/health` + 关键接口抽测）。
3. 更新本文档「当前状态 / 最近改动 / 已知坑」。
4. 若改了 `.env` 结构或启动方式，同步更新第二节。
