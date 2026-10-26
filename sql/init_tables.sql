-- =====================================================================
-- 掌控校园 (Campus Master) —— MySQL 建表脚本（在华为云 RDS 上执行）
-- 执行方式（新手推荐）：
--   华为云控制台 → 云数据库 RDS → 找到你的实例 → 点「登录」（DAS 数据管理）
--   → 打开 SQL 查询窗口 → 粘贴本文件全部内容 → 执行
-- =====================================================================

-- 0. 创建数据库：utf8mb4 才能正常存中文，千万别用默认字符集
CREATE DATABASE IF NOT EXISTS campus_master
    DEFAULT CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE campus_master;

-- ---------------------------------------------------------------------
-- 表 1：notices 通知表（服务模块1：AI 校园情报官）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notices (
    id           INT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '主键，自增',
    title        VARCHAR(200) NOT NULL                COMMENT '通知标题',
    content      TEXT         NOT NULL                COMMENT '通知正文原文',
    summary      VARCHAR(500) DEFAULT NULL            COMMENT 'AI 生成的一句话摘要',
    ai_source    VARCHAR(100) DEFAULT NULL            COMMENT 'AI 识别出的来源，如: 教务处官网',
    source_url   VARCHAR(500) DEFAULT NULL            COMMENT '通知原文链接（溯源凭证）',
    publish_date DATE         DEFAULT NULL            COMMENT '通知发布日期',
    created_at   DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间'
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci
  COMMENT = '通知表（AI 校园情报官）';

-- 设计说明：在你给的 5 个字段基础上补了 3 个——
--   summary / ai_source：模块1 大模型要输出「摘要 + 来源」，必须有字段存它；
--   created_at：通用习惯，靠 ORDER BY created_at DESC 实现「最新 5 条」。

-- ---------------------------------------------------------------------
-- 表 2：posts 帖子表（模块2：经验帖是知识图谱的数据来源）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS posts (
    id         INT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '主键，自增',
    title      VARCHAR(200) NOT NULL COMMENT '帖子标题',
    content    TEXT         NOT NULL COMMENT '帖子正文',
    author     VARCHAR(50)  NOT NULL DEFAULT '匿名' COMMENT '发帖人',
    likes      INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '点赞数',
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '发帖时间'
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci
  COMMENT = '经验帖子表（知识智库）';

-- ---------------------------------------------------------------------
-- 表 3：kg_nodes 知识图谱节点表（服务模块2：学习路径推荐）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kg_nodes (
    id          INT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '主键，自增',
    name        VARCHAR(100) NOT NULL COMMENT '节点名，如: C语言',
    type        VARCHAR(20)  NOT NULL DEFAULT 'course' COMMENT '节点类型: course=课程 / contest=竞赛 / skill=经验技能',
    description VARCHAR(500) DEFAULT NULL COMMENT '节点介绍（前端鼠标悬停时展示）',
    source_post_id INT UNSIGNED DEFAULT NULL COMMENT '由哪篇帖子抽取产生(NULL=手工演示数据)',
    created_at  DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
    UNIQUE KEY uk_node_name (name) COMMENT '同名节点只允许存在一个'
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci
  COMMENT = '知识图谱节点表';

-- ---------------------------------------------------------------------
-- 表 4：kg_edges 知识图谱边表（存"节点指向节点"的关系）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS kg_edges (
    id             INT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '主键，自增',
    source_node_id INT UNSIGNED NOT NULL COMMENT '边的起点 → kg_nodes.id（如: C语言）',
    target_node_id INT UNSIGNED NOT NULL COMMENT '边的终点 → kg_nodes.id（如: 蓝桥杯）',
    relation       VARCHAR(50)  NOT NULL DEFAULT 'related' COMMENT '关系: prerequisite=前置 / related=相关 / contains=包含',
    created_at     DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
    UNIQUE KEY uk_edge (source_node_id, target_node_id, relation),
    CONSTRAINT fk_edge_source FOREIGN KEY (source_node_id) REFERENCES kg_nodes (id),
    CONSTRAINT fk_edge_target FOREIGN KEY (target_node_id) REFERENCES kg_nodes (id)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci
  COMMENT = '知识图谱边表';

-- ---------------------------------------------------------------------
-- 表 5：user_profiles 个人中心（扩展表，赛题规定的 4 张表字段一个没动）
--   存学生的身份角色，用来驱动「图谱按身份分层 + 学习路径默认值」
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_profiles (
    id         INT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '主键，自增',
    nickname   VARCHAR(50)  NOT NULL COMMENT '昵称（站内唯一，前端 localStorage 存它当登录态）',
    school     VARCHAR(60)  DEFAULT NULL COMMENT '就读学校，如: 杭州电子科技大学（决定情报官抓哪些官方通知源）',
    grade      VARCHAR(20)  DEFAULT NULL COMMENT '年级，如: 大二',
    major      VARCHAR(50)  DEFAULT NULL COMMENT '专业，如: 计算机科学与技术',
    role       VARCHAR(20)  NOT NULL DEFAULT 'freshman' COMMENT '身份角色: freshman/contest/jobseeker/postgrad',
    goal       VARCHAR(100) DEFAULT NULL COMMENT '目标，如: 拿蓝桥杯省一',
    email      VARCHAR(100) DEFAULT NULL COMMENT '联系方式（用于风险预警提醒）',
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '建档时间',
    updated_at DATETIME     DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后修改时间',
    UNIQUE KEY uk_profile_nickname (nickname)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci
  COMMENT = '个人中心资料表';

-- ---------------------------------------------------------------------
-- 表 6：risk_logs 风险台账（安全雷达每次扫描留一条，可回溯）
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS risk_logs (
    id         INT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '主键，自增',
    scene      VARCHAR(20)  NOT NULL DEFAULT 'job' COMMENT '场景: job=求职鉴坑 / fraud=聊天鉴诈 / notice=通知排查',
    nickname   VARCHAR(50)  DEFAULT NULL COMMENT '提交人昵称（可空=未登录）',
    excerpt    VARCHAR(200) NOT NULL COMMENT '送检内容摘要（只存前 200 字，不留原文避免敏感信息堆积）',
    level      VARCHAR(20)  NOT NULL COMMENT '风险等级: high_risk/medium_risk/low_risk/likely_safe',
    score      TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '欺诈可能性 0~100',
    risk_types VARCHAR(300) DEFAULT NULL COMMENT '命中的风险类型，逗号分隔',
    engine     VARCHAR(20)  NOT NULL DEFAULT 'local-rules' COMMENT '判定引擎: llm / local-rules',
    skill      VARCHAR(80)  DEFAULT NULL COMMENT '扫描时选用的检测技能名（可空=全条款库）',
    cited_articles VARCHAR(300) DEFAULT NULL COMMENT '本次判词引用的条款（文件+条款号，可回溯到 handbook_articles）',
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '扫描时间',
    KEY idx_log_created (created_at)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci
  COMMENT = '安全雷达风险台账';

-- ---------------------------------------------------------------------
-- 表 7：study_list 个人学习清单（知识图谱里点节点加进来的，AI 按它出规划）
--   节点名直接对应 kg_nodes.name，图谱改了名清单里就是孤儿项，接口里会标出来
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS study_list (
    id         INT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '主键，自增',
    nickname   VARCHAR(50)  NOT NULL COMMENT '归属昵称（与 user_profiles.nickname 同一套）',
    node_name  VARCHAR(100) NOT NULL COMMENT '图谱节点名，如: 数据结构 / 蓝桥杯',
    node_type  VARCHAR(20)  NOT NULL DEFAULT 'course' COMMENT '节点类型快照: course/contest/skill',
    status     VARCHAR(10)  NOT NULL DEFAULT 'todo' COMMENT '进度: todo=待学 / doing=在学 / done=已学完',
    added_at   DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '加入时间',
    UNIQUE KEY uk_study_nick_node (nickname, node_name),
    KEY idx_study_nick (nickname)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci
  COMMENT = '个人学习清单';

-- ---------------------------------------------------------------------
-- 表 8：handbook_articles 条款库（安全雷达的「有理有据」全靠它）
--   一行一条**逐字原文**，判词里引用时必须一字不改地贴出来；
--   keywords 是给本地关键词检索用的（不引向量库，见 LOCAL_SETUP 的说明），
--   verified=0 / enabled=0 的行表示「还没对上官方原文」，默认不参与引用——
--   宁可少一条，不可错一条：没核实的条款绝不能进判词。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS handbook_articles (
    id         INT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '主键，自增',
    doc_title  VARCHAR(100) NOT NULL COMMENT '文件全名，如: 中华人民共和国劳动合同法 / XX大学学生手册(2024版)',
    doc_year   SMALLINT     DEFAULT NULL COMMENT '现行版本的通过/修订年份（引条款时必须同一版）',
    article_no VARCHAR(24)  NOT NULL COMMENT '条款号，如: 第九条 / 第四十一条第(四)项',
    title      VARCHAR(120) NOT NULL DEFAULT '' COMMENT '条款小标题，没有就留空',
    text       TEXT         NOT NULL COMMENT '逐字原文（判词里直接引用，不许改写）',
    scene      VARCHAR(20)  NOT NULL DEFAULT 'all' COMMENT '适用场景: job=求职鉴坑 / fraud=聊天鉴诈 / notice=通知排查 / all=通用',
    risk_type  VARCHAR(60)  NOT NULL DEFAULT '' COMMENT '对应风险类型名（与扫描结果 risk_types 对齐）',
    keywords   VARCHAR(300) NOT NULL DEFAULT '' COMMENT '命中关键词，逗号分隔（本地检索用）',
    source     VARCHAR(20)  NOT NULL DEFAULT 'law' COMMENT '来源层级: law=国家法律 / regulation=部委规章文件 / judicial=两高司法文件 / school=校方手册',
    url        VARCHAR(300) DEFAULT NULL COMMENT '可核对的权威原文链接',
    trust      TINYINT UNSIGNED NOT NULL DEFAULT 80 COMMENT '可信度 0~100: 法律>部委文件>校方手册',
    verified   TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '1=已逐字对上官方原文；0=存疑',
    enabled    TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '1=参与检索；导入口新加的条款先置 0，人工核过再放开',
    note       VARCHAR(300) DEFAULT NULL COMMENT '版本/存疑备注（如「网络安全法2025修正后旧27条已变29条」）',
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '入库时间',
    UNIQUE KEY uk_hb_doc_article (doc_title, article_no),
    KEY idx_hb_scene (scene, enabled)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci
  COMMENT = '安全雷达条款库（法律法规 + 教育部规章 + 校方手册）';

-- ---------------------------------------------------------------------
-- 表 9：notice_sources 官方通知源注册表（情报官的「多方官方通知」从这来）
--   一行一个「学校 × 部门」的通知列表页；抓取器按通用规则解析列表，
--   解析对不上就先把 enabled 关掉，别让坏源刷屏或刷进脏数据。
--   notices 是赛题表不能加列，「官方来源」用 source_url 以 http 开头来区分手动贴入。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notice_sources (
    id            INT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '主键，自增',
    school        VARCHAR(60)  NOT NULL COMMENT '归属学校，与 user_profiles.school 同一套叫法',
    dept          VARCHAR(40)  NOT NULL COMMENT '部门名，如: 教务处 / 就业指导中心（入库时写进 notices.ai_source）',
    url           VARCHAR(300) NOT NULL COMMENT '通知列表页地址（抓取器抓这一页）',
    enabled       TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '1=参与抓取；0=解析失效或栏目改版，先关掉',
    note          VARCHAR(200) DEFAULT NULL COMMENT '备注：栏目名/为什么加它/改版时要看什么',
    last_fetch_at DATETIME     DEFAULT NULL COMMENT '上次抓取时间',
    last_new      INT          NOT NULL DEFAULT 0 COMMENT '上次抓到几条新通知',
    UNIQUE KEY uk_src_school_dept (school, dept),
    KEY idx_src_school (school, enabled)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci
  COMMENT = '官方通知源注册表（按学校组织，情报官抓取的依据）';

-- ---------------------------------------------------------------------
-- 表 10：post_media 帖子图片附件（论坛发帖配图用）
--   赛题规定的 posts 表结构不能动，图片单独一张表挂 post_id；
--   文件本体存服务器 uploads/ 目录，表里只存可访问的 URL。
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS post_media (
    id         INT UNSIGNED AUTO_INCREMENT PRIMARY KEY COMMENT '主键，自增',
    post_id    INT UNSIGNED NOT NULL COMMENT '归属帖子 posts.id',
    url        VARCHAR(300) NOT NULL COMMENT '图片地址（/uploads/…，由 POST /upload 返回）',
    sort       TINYINT      NOT NULL DEFAULT 0 COMMENT '展示顺序（上传先后）',
    created_at DATETIME     DEFAULT CURRENT_TIMESTAMP COMMENT '上传时间',
    KEY idx_media_post (post_id)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4
  COLLATE = utf8mb4_unicode_ci
  COMMENT = '帖子图片附件（不占赛题 posts 表的列）';

-- ---------------------------------------------------------------------
-- 演示数据：建完表立刻有东西可查、前端有图可画（熟悉后可删）
-- ---------------------------------------------------------------------
INSERT INTO notices (title, content, summary, ai_source, source_url, publish_date) VALUES
('关于举办蓝桥杯校内选拔赛的通知',
 '蓝桥杯全国软件和信息技术专业人才大赛校内选拔赛将于下月第一个周六举行，请有意向的同学在教务系统报名。',
 '蓝桥杯校内选拔赛下月第一个周六举行，教务系统报名',
 '教务处官网', 'https://jwc.example.edu.cn/notice/1001', '2026-10-20'),
('2026年寒假放假及宿舍安排通知',
 '学生于1月15日起放寒假，宿舍需在离校前登记，留校学生请提前向辅导员报备。',
 '1月15日起放寒假，离校登记+留校报备',
 '学生处官网', 'https://xsc.example.edu.cn/notice/1002', '2026-10-22');

INSERT INTO kg_nodes (name, type, description) VALUES
('C语言',      'course',  '大一程序设计入门课，蓝桥杯 C/C++ 组的前置知识'),
('蓝桥杯',    'contest', '全国软件和信息技术专业人才大赛，含 C/C++、Java 等组别'),
('Python基础', 'course',  '数据处理与爬虫的入门语言'),
('数据分析',   'skill',   '用 Pandas 等工具从数据中提炼结论的能力'),
('数据结构',   'course',  '算法学习的核心基础课，蓝桥杯/考研/求职笔试三必需'),
('Java基础',   'course',  '面向对象入门，蓝桥杯 Java 组与后端实习的主流语言'),
('实习',       'skill',   '企业真实项目经历，秋招简历的核心竞争力'),
('考研英语',   'course',  '硕士研究生招生考试英语科目，建议大二开始背单词');

-- 用子查询按「节点名」自动找到对应的 id 再插入边（防止手写 id 写错）
INSERT INTO kg_edges (source_node_id, target_node_id, relation)
SELECT a.id, b.id, 'prerequisite'
FROM kg_nodes a, kg_nodes b
WHERE (a.name = 'C语言' AND b.name = '蓝桥杯')
   OR (a.name = 'Python基础' AND b.name = '数据分析')
   OR (a.name = 'C语言' AND b.name = '数据结构')
   OR (a.name = '数据结构' AND b.name = '蓝桥杯')
   OR (a.name = 'Java基础' AND b.name = '实习')
   OR (a.name = '数据结构' AND b.name = '实习');

INSERT INTO kg_edges (source_node_id, target_node_id, relation)
SELECT a.id, b.id, 'related'
FROM kg_nodes a, kg_nodes b
WHERE a.name = 'C语言' AND b.name = 'Python基础';

INSERT INTO kg_edges (source_node_id, target_node_id, relation)
SELECT a.id, b.id, 'contains'
FROM kg_nodes a, kg_nodes b
WHERE a.name = '蓝桥杯' AND b.name = '数据结构';

-- ---------------------------------------------------------------------
-- 演示数据：经验帖（模块2 的图谱数据来源）
-- ---------------------------------------------------------------------
INSERT INTO posts (title, content, author, likes) VALUES
('打蓝桥杯的正确顺序', '想拿蓝桥杯省一，C语言要先学，学完C语言才能啃数据结构，数据结构刷透了再去打比赛事半功倍。', '计科2301张同学', 42),
('数据分析入门路线', 'Python基础是数据分析的基础，建议先把Python基础打牢，再学Pandas做数据分析。', '数据2202李同学', 28),
('大二找实习经验分享', '数据结构是找实习的硬门槛，Java基础和数据结构都过关后再投实习，简历上要有能讲的项目。', '软工2102王同学', 66);

-- ---------------------------------------------------------------------
-- 演示数据：个人中心 + 安全雷达台账（都是明显编的样例，只为了让页面一打开就有内容）
--   昵称特意复用上面经验帖的作者，这样「我的发帖」「我的风险记录」一进来就有东西可看
-- ---------------------------------------------------------------------
INSERT INTO user_profiles (nickname, grade, major, role, goal, email) VALUES
('计科2301张同学', '2024级', '计算机科学与技术', 'contest', '蓝桥杯省一', 'zhangsan@example.edu.cn'),
('示例·李四', '2023级', '软件工程', 'jobseeker', '大三暑期实习', 'lisi@example.edu.cn');

INSERT INTO risk_logs (scene, nickname, excerpt, level, score, risk_types, engine, cited_articles) VALUES
('job', '计科2301张同学', '【演示数据】HR说兼职日薪300，入职前要先交200元押金和199元培训费，不用签合同。', 'high_risk', 86, '交押金/保证金、收费培训、不签合同', 'local-rules', '中华人民共和国劳动合同法第九条、普通高等学校学生管理规定第四十五条'),
('fraud', '示例·李四', '【演示数据】对方自称辅导员，要求把短信验证码发过去并点链接登记银行卡。', 'high_risk', 74, '索要验证码/账号密码、疑似钓鱼链接', 'local-rules', '中华人民共和国反电信网络诈骗法第二十五条、中华人民共和国网络安全法第二十九条'),
('notice', '计科2301张同学', '【演示数据】群里转发的高速退税通知，要求24小时内登录非学校域名填写银行卡。', 'medium_risk', 38, '中奖/退税/补贴骗局、疑似钓鱼链接', 'local-rules', '中华人民共和国反电信网络诈骗法第三十一条'),
('job', '示例·李四', '【演示数据】学长推荐的实验室助研岗，写明工作量与劳务费发放方式，不收费不扣证。', 'likely_safe', 0, '', 'local-rules', NULL);

-- ---------------------------------------------------------------------
-- 演示数据：个人学习清单（图谱页右下角那张「AI 规划」面板，一打开就有计划可看）
--   昵称复用上面两位演示同学：改完身份后进图谱页把昵称填成一样的就能看到这份清单
--   INSERT IGNORE 是因为 (nickname,node_name) 唯一，脚本重复执行不会报主键冲突
-- ---------------------------------------------------------------------
INSERT IGNORE INTO study_list (nickname, node_name, node_type, status) VALUES
('计科2301张同学', 'C语言',    'course',  'done'),
('计科2301张同学', '数据结构', 'course',  'doing'),
('计科2301张同学', '蓝桥杯',   'contest', 'todo'),
('示例·李四',      'Java基础', 'course',  'todo'),
('示例·李四',      '实习',     'skill',   'todo');

-- ---------------------------------------------------------------------
-- 演示数据：官方通知源（情报官「多方官方通知」的种子，全部是真实栏目页）
--   三个源都人工验证过列表页可静态解析；杭电研究生院/图书馆页面是 JS 渲染，
--   通用抓取器读不到，先不录进来（要加新源：INSERT 一行就能抓，注意先人工看一眼页面）。
-- ---------------------------------------------------------------------
INSERT IGNORE INTO notice_sources (school, dept, url, enabled, note) VALUES
('杭州电子科技大学', '学校通知公告', 'https://www.hdu.edu.cn/tzgg/list.htm', 1,
 '学校主页通知公告栏目；链接带 /20xx/xxxx/cxxx 序号，日期可从 URL 解出'),
('杭州电子科技大学', '教务处', 'https://jwc.hdu.edu.cn/13022/list.htm', 1,
 '教务处「通知公告」栏目，栏目号 13022 改版时要跟着改'),
('杭州电子科技大学', '就业指导中心', 'https://job.hdu.edu.cn/', 1,
 '就业信息网首页静态区带 tag/tzgg 的公告；详情页为 /news/view/aid/…');
