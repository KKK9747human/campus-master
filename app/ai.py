"""
=====================================================================
 掌控校园 —— AI 能力层（模块1/2/3 的大模型调用都集中在这里）
=====================================================================
 优先调用华为云 MaaS 大模型 API（OpenAI 兼容接口）；
 若 .env 未配置 MAAS_API_KEY 或调用失败，自动降级到内置的
 「本地规则引擎」，保证评委现场没网、没 Key 也能演示全流程。

 三个对外函数：
   extract_notice(text)         模块1：通知 → {summary, source, time, event}
   extract_triples(post_text)   模块2：经验帖 → 知识图谱三元组（节点+边）
   analyze_job_chat(chat_text)  模块3：兼职聊天记录 → 风险判定
"""

import os
import re
import json

import httpx
from dotenv import load_dotenv

load_dotenv()

MAAS_API_KEY = os.getenv("MAAS_API_KEY", "").strip()
MAAS_MODEL = os.getenv("MAAS_MODEL", "deepseek-v3-2324")
MAAS_BASE_URL = os.getenv(
    "MAAS_BASE_URL", "https://api.cn-east-3.maas.com.cn/compatible-mode/v1"
)


class AINotConfigured(Exception):
    """没配 API Key，或 MaaS 调用失败 → 触发本地降级"""


# ---------------------------------------------------------------------
# 一、Prompt 定义（赛题要求模块1严格按 {"summary":"","source":""} JSON 输出）
# ---------------------------------------------------------------------
SYS_JSON_ONLY = (
    "你是高校信息处理助手。只输出一个合法 JSON 对象，"
    "不要 markdown 代码块，不要任何解释文字。"
)

PROMPT_NOTICE = """请从下面的校园通知中提取核心信息，严格按此 JSON 格式输出：
{"summary": "一句话摘要，不超过50字", "source": "发布来源，如: 教务处官网", "time": "通知中的关键时间", "event": "核心事件", "highlights": ["必须记住的要点，1~3条"]}
规则：
1. summary 必须概括「谁+做什么+何时」；
2. source 只依据文本判断，判断不了就填 "未知来源"，禁止编造；
3. time/event 找不到对应内容时填空字符串。
通知标题：{title}
通知正文：{content}"""

PROMPT_TRIPLES = """从下面的校园经验帖中提取知识图谱三元组，严格按此 JSON 格式输出：
{"nodes": [{"name": "节点名", "type": "course|contest|skill 三选一", "description": "一句话介绍"}],
 "edges": [{"source": "起点节点名", "target": "终点节点名", "relation": "prerequisite|related|contains 三选一"}]}
规则：
1. course=课程, contest=竞赛, skill=经验/技能/证书；
2. prerequisite 表示"先学 source 才能学 target"（source 是前置）；
3. nodes 最多 6 个，edges 最多 6 条，宁缺毋滥，禁止编造文本中没有的关系；
4. 边的两端必须出现在 nodes 列表里。
经验帖标题：{title}
经验帖正文：{content}"""

PROMPT_JOB_RISK = """你是大学生求职反诈专家。分析下面的兼职/实习 HR 聊天记录，严格按此 JSON 格式输出：
{"level": "high_risk|medium_risk|low_risk|likely_safe", "score": 0到100的欺诈可能性整数, "risks": [{"type": "风险类型", "quote": "聊天记录原文证据", "reason": "为什么危险"}], "advice": "给学生的行动建议，不超过60字"}
高危特征：以任何名义交钱（押金/保证金/培训费/服装费）、扣证件、不签合同、先干活后谈薪、以招聘为诱饵刷单/贷款、收费内推、超长试用。
medium_risk 特征：只谈钱不谈工作内容、承诺与岗位明显不匹配、催促立刻交材料。
risks 只列有原文证据的项，无风险则给空数组。"""


# ---------------------------------------------------------------------
# 二、MaaS 调用（OpenAI 兼容 chat/completions）
# ---------------------------------------------------------------------
def ask_json(system: str, user: str) -> dict:
    """调用大模型并要求返回 JSON dict；未配置或失败抛 AINotConfigured"""
    if not MAAS_API_KEY:
        raise AINotConfigured("未配置 MAAS_API_KEY")
    try:
        resp = httpx.post(
            f"{MAAS_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {MAAS_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": MAAS_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.1,
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        raise AINotConfigured(f"MaaS 调用失败: {e}")
    return parse_json_loose(content)


def parse_json_loose(text: str) -> dict:
    """容错解析：剥掉 ```json 代码块、截取首个 {...} 片段"""
    text = text.strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        raise AINotConfigured("模型输出中未找到 JSON")
    return json.loads(m.group(0))


# ---------------------------------------------------------------------
# 三、模块1：通知抽取（LLM → 降级规则引擎）
# ---------------------------------------------------------------------
SOURCE_KEYWORDS = [
    "教务处", "学生处", "学工部", "研究生院", "就业中心", "就业指导中心",
    "图书馆", "后勤", "宿管", "团委", "信息化中心", "网络中心", "学院", "财务部",
]


def extract_notice(title: str, content: str) -> dict:
    user = PROMPT_NOTICE.replace("{title}", title).replace("{content}", content)
    try:
        d = ask_json(SYS_JSON_ONLY, user)
    except AINotConfigured:
        return _notice_by_rules(title, content)
    if not d.get("summary"):
        return _notice_by_rules(title, content)
    d.setdefault("source", "未知来源")
    d.setdefault("time", "")
    d.setdefault("event", "")
    d.setdefault("highlights", [])
    d["engine"] = "llm"
    return d


def _notice_by_rules(title: str, content: str) -> dict:
    """本地规则降级：摘要=标题+首句；来源=关键词匹配；时间=日期/周几模式"""
    text = content.strip()
    sentences = [s for s in re.split(r"[。！？;；]", text) if s.strip()]
    first = sentences[0].strip() if sentences else ""
    summary = first if (not first or first in title) else f"{title}：{first}"
    summary = summary[:50]

    source = "未知来源"
    for kw in SOURCE_KEYWORDS:
        if kw in title or kw in content:
            source = f"{kw}官网"
            break

    time = ""
    m = re.search(
        r"\d{1,2}月\d{1,2}日|\d{4}年\d{1,2}月|\d{1,2}月[一二三四五六七八九十]+旬?"
        r"|下周[一二三四五六日]|本周[一二三四五六日]|下个月|明天|今天",
        f"{title} {content}",
    )
    if m:
        time = m.group(0)

    event = title.lstrip("关于").rstrip("的通知通知") or summary
    return {
        "summary": summary,
        "source": source,
        "time": time,
        "event": event,
        "highlights": [s.strip() for s in sentences if any(c.isdigit() for c in s)][:3],
        "engine": "local-rules",
    }


# 三点五、官方源通知的一句话摘要（列表抓取入库后，点开才抓详情页生成）
PROMPT_OFFICIAL_SUMMARY = """你是校园通知编辑。下面是一则高校官方通知，请写一句给大学生看的摘要，严格按此 JSON 输出：
{"summary": "一句话，不超过42字，说清谁针对谁做什么、关键时间或要办的动作"}
规则：只依据给出的标题和正文，禁止编造；正文里没有出现的时间不要写。
通知标题：{title}
通知正文：{text}"""


def summarize_official(title: str, text: str) -> dict:
    """官方通知详情页 → 一句话摘要；LLM 不可用就降级为标题+首句"""
    user = PROMPT_OFFICIAL_SUMMARY.replace("{title}", title).replace("{text}", text[:1200])
    try:
        d = ask_json(SYS_JSON_ONLY, user)
    except AINotConfigured:
        pass
    else:
        s = str(d.get("summary") or "").strip()
        if s:
            return {"summary": s[:42], "engine": "llm"}
    sentences = [x for x in re.split(r"[。！？;；]", text) if x.strip()]
    first = sentences[0].strip() if sentences else ""
    summary = f"{title}：{first}" if first and first not in title else (first or title)
    return {"summary": summary[:42], "engine": "local-rules"}


# ---------------------------------------------------------------------
# 四、模块2：三元组抽取（LLM → 降级规则引擎）
# ---------------------------------------------------------------------
TYPE_RULES = [
    (("杯", "大赛", "比赛", "竞赛"), "contest"),
    (("课", "基础", "入门", "语言", "数学", "高数", "线代", "英语", "数据结构", "算法"), "course"),
]


def guess_type(name: str) -> str:
    for kws, t in TYPE_RULES:
        if any(k in name for k in kws):
            return t
    return "skill"


# 捕获组里可能混入的虚词/动词前缀（长词放前面，避免先剥短词造成错切）
_NODE_STOPWORDS = [
    "建议先", "必须先", "应该先", "参加", "掌握", "学习", "啃透", "啃", "打牢",
    "做", "投", "打", "拿", "搞", "学", "写", "练",
    "先学", "再学", "要把", "要", "想", "得", "应", "把", "先", "再", "都", "过", "去", "能", "才",
]


def extract_triples(title: str, content: str, known_names=None) -> dict:
    user = PROMPT_TRIPLES.replace("{title}", title).replace("{content}", content)
    try:
        d = ask_json(SYS_JSON_ONLY, user)
        assert isinstance(d.get("nodes"), list) and d["nodes"]
    except (AINotConfigured, AssertionError):
        return _triples_by_rules(title, content, known_names)
    d["engine"] = "llm"
    return d


def _resolve_alias(name: str, known: list) -> str:
    """捕获片段常被贪婪正则吞掉首字（'考研数学'→'研数学'）：
    若它是某个已有节点名的严格子串，归并到最长匹配者，避免图谱长出一堆残缺节点"""
    best = ""
    for k in known:
        if name != k and name in k and len(k) > len(best):
            best = k
    return best or name


def _clean_node(name: str) -> str:
    """剥掉捕获组里混入的虚词/动词前缀，如 '要C语言'→'C语言'、'啃数据结构'→'数据结构'"""
    changed = True
    while changed:
        changed = False
        for sw in _NODE_STOPWORDS:
            if name.startswith(sw) and len(name) - len(sw) >= 2:
                name = name[len(sw):]
                changed = True
    return name


def _triples_by_rules(title: str, content: str, known_names=None) -> dict:
    """本地规则降级：匹配「A要先学B」「学完A才能B」「A是B的基础」等句式"""
    known = list(known_names or [])
    text = f"{title}。{content}"
    patterns = [
        (r"([\u4e00-\u9fa5\w+\#\.]{2,12})要先学([\u4e00-\u9fa5\w+\#\.]{2,12})", "prerequisite", 2),
        (r"学完([\u4e00-\u9fa5\w+\#\.]{2,12})(?:之后|后)?才能([\u4e00-\u9fa5\w+\#\.]{2,12})", "prerequisite", 2),
        (r"([\u4e00-\u9fa5\w+\#\.]{2,12})是([\u4e00-\u9fa5\w+\#\.]{2,12})的(?:基础|前置|前提)", "prerequisite", 2),
        (r"想参加([\u4e00-\u9fa5\w+\#\.]{2,12})建议先掌握([\u4e00-\u9fa5\w+\#\.]{2,12})", "prerequisite", 2),
        (r"([\u4e00-\u9fa5\w+\#\.]{2,12})和([\u4e00-\u9fa5\w+\#\.]{2,12})(?:关系|内容)?很相关", "related", 2),
        (r"推荐(?:学完|先学)([\u4e00-\u9fa5\w+\#\.]{2,12})再学([\u4e00-\u9fa5\w+\#\.]{2,12})", "prerequisite", 2),
    ]
    nodes, edges, seen = [], [], set()

    def add_node(name, desc):
        name = _clean_node(name.strip())
        if name and len(name) >= 2 and name not in seen:
            seen.add(name)
            nodes.append({"name": name, "type": guess_type(name), "description": desc[:100]})
        return name

    def norm(name, m, gi):
        name = _clean_node(name.strip())
        hit = _resolve_alias(name, known)
        if hit != name:
            return hit
        # 贪婪正则常吞掉首字（'考研数学'→'研数学'）：回粘捕获位置前的 1~2 个字再对已有节点求值
        back = text[max(0, m.start(gi) - 2):m.start(gi)]
        for cut in (1, 2):
            if len(back) >= cut:
                cand = back[-cut:] + name
                if cand in known:
                    return cand
        return name

    for pat, rel, n in patterns:
        for m in re.finditer(pat, text):
            gs = [g for g in m.groups() if g][:n]
            gidx = [i for i, g in enumerate(m.groups()) if g][:n]
            if len(gs) < 2:
                continue
            groups = [norm(gs[i], m, gidx[i]) for i in range(len(gs))]
            if any(len(g) < 2 for g in groups):
                continue
            for g in groups:
                add_node(g, content[:100])
            # 句式「A要先学B」= B 是 A 的前置 → 边 B -> A
            if pat in (patterns[0][0], patterns[3][0]):
                src, dst = groups[1], groups[0]
            else:
                src, dst = groups[0], groups[1]
            key = (src, dst, rel)
            if src != dst and key not in {(e["source"], e["target"], e["relation"]) for e in edges}:
                edges.append({"source": src, "target": dst, "relation": rel})

    return {"nodes": nodes[:6], "edges": edges[:6], "engine": "local-rules"}


# ---------------------------------------------------------------------
# 五、模块3：风险判定（求职鉴坑 + 通用鉴诈，LLM → 降级规则引擎）
# ---------------------------------------------------------------------
_TIER_SCORE = {"high": 45, "medium": 20, "low": 8}

RISK_RULES = [
    ("交押金/保证金", [r"押金", r"保证金"], "high"),
    ("收费培训", [r"培训费", r"交.*?元培训", r"缴费.*?培训"], "high"),
    ("服装费/体检费/材料费", [r"服装费", r"体检费", r"材料费", r"工服费"], "high"),
    ("扣押证件", [r"扣.*?证件", r"抵押.*?证", r"上交.*?身份证", r"身份证原件", r"身份证.*?保管"], "high"),
    ("刷单/打字等典型骗局", [r"刷单", r"刷销量", r"打字员", r"垫付"], "high"),
    ("贷款/传销风险", [r"贷款", r"分期", r"拉人头", r"发展下线"], "high"),
    ("不签合同", [r"不签合同", r"不用签合同", r"没有合同", r"无需协议", r"口头约定"], "high"),
    ("先干活后谈钱", [r"先干", r"试岗.*?天", r"免费.*?试.*?天", r"先做.*?再说薪"], "medium"),
    ("收费内推", [r"内推费", r"保offer", r"包就业.*?费"], "medium"),
    ("超长试用期", [r"试用期.*?个月", r"试用.*?30天"], "medium"),
    ("薪酬好得反常", [r"日薪.*?[5-9]\d\d", r"月入过万", r"轻松.*?过万", r"日结\d{3,}"], "low"),
]

# 非求职场景（冒充师生、盗号、钓鱼链接、校园贷等）的校园常见诈骗特征
FRAUD_RULES = [
    ("索要验证码/账号密码", [r"验证码[^\n]{0,6}(发我|给我|提供|截图)", r"(账号密码|登录密码).{0,4}(发|给|要)", r"帮[我你]?[们]?[登注]录"], "high"),
    ("假冒老师/辅导员收费", [r"(老师|辅导员|班主任|助教|学长|学姐)[^\n]{0,20}(缴费|交钱|转账|汇款|打款)"], "high"),
    ("诱导私下转账", [r"(微信|支付宝|银行卡)[^\n]{0,6}(转账|打款|汇钱)", r"打款到", r"转到这[个张]?卡", r"先转[给你]"], "high"),
    ("冒充同学借钱救急", [r"(出事|急用|住院|被抓)[^\n]{0,10}(帮|借|转|汇)"], "high"),
    ("校园贷/裸贷", [r"校园贷", r"裸贷", r"(学生证|身份证)[^\n]{0,4}拍[照]?[给]?"], "high"),
    ("中奖/退税/补贴骗局", [r"中奖", r"退税", r"(助学金|奖学金|补贴)[^\n]{0,10}(点击|链接|领取)", r"退款[^\n]{0,6}验证码"], "high"),
    ("刷单返利话术", [r"做任务[^\n]{0,6}(返|赚|结)", r"返[佣款][^\n]{0,4}(先|垫)", r"(日赚|躺赚)\d"], "high"),
    ("投资荐股/杀猪盘", [r"(带你|内幕|稳赚)[^\n]{0,4}(投|赚)", r"投资平台", r"荐股", r"内部[渠道额度]"], "medium"),
    ("把人引到别的 App 聊", [r"加[个]?[QqQQ]{2}[群号]", r"下载[个]?[^\n]{0,8}(App|APP|软件)[^\n]{0,4}聊", r"换个[地软]方[聊说]"], "medium"),
    # 帮信罪：学生最容易「顺手赚一笔」踩进去的坑，条款库里有反电诈法第三十一条 + 校规第五十二条兜着
    ("出租出借银行卡/账号", [r"(租|借|收购|卖|收)[^\n]{0,8}(银行卡|手机卡|电话卡|支付账户|微信|qq号?|二维码)",
      r"(银行卡|手机卡|电话卡|支付账户|微信)[^\n]{0,10}(租|借|卖|走流水)", r"跑分", r"走[个]?流水"], "high"),
    # 群里代收班费/资料费：真实通知也收钱，所以只定中危，靠「名目 + 私人收款渠道」区分
    ("通知里的可疑代收费用", [r"(资料费|书本费|打印费|防暑费|代办费|内推费|班费)",
      r"扫码[^\n]{0,6}(缴|付|收|款)", r"(缴|付)[^\n]{0,4}(到|进)[^\n]{0,8}(微信|支付宝|个人账户)"], "medium"),
    ("制造紧急感施压", [r"(立刻|马上|尽快|赶紧)[^\n]{0,6}(交|转|付|发)", r"别告诉", r"保[密密]"], "medium"),
    ("异常链接/非学校域名", [], "medium"),   # 由 _phishing_risk 单独判，占位保持结构一致
]

JOB_ADVICE = {
    "high_risk": "立即停止联系，不要转账、不交证件。可拨打学校就业中心电话或 110 核实。",
    "medium_risk": "存在可疑特征，先书面确认岗位职责与薪酬结构，坚持签订协议后再上岗。",
    "low_risk": "仅有轻微可疑点，留意对方是否愿意签订书面协议即可。",
    "likely_safe": "未发现明显诈骗特征。仍建议核实企业资质、坚持签书面合同、任何收费要求一律拒绝。",
}
FRAUD_ADVICE = {
    "high_risk": "先停手：不回拨、不点链接、不转钱。用官方渠道（辅导员工号/学校官网电话）反向核实，必要时报警。",
    "medium_risk": "可疑但不足以定性，坚持「不离开官方平台、不交钱、不给验证码」三不原则，再找同学或老师确认。",
    "low_risk": "只有轻微可疑点，留个心眼即可，涉及钱和验证码时再核实一次。",
    "likely_safe": "暂未见明显诈骗特征。凡是催你转账、要验证码、点陌生链接的，一律当诈骗处理。",
}


def _rules_verdict(text: str, rules: list, advice: dict, extra_risks=None) -> dict:
    """规则引擎通用打分：高危 45 / 中危 20 / 低危 8，封顶 95"""
    risks, score = [], 0
    for rtype, patterns, tier in rules:
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                score += _TIER_SCORE[tier]
                risks.append({"type": rtype, "quote": m.group(0),
                              "reason": f"命中典型诈骗特征「{rtype}」"})
                break
    for r in (extra_risks or []):
        score += _TIER_SCORE.get(r.pop("_tier", "medium"), 20)
        risks.append(r)
    return _finalize(risks, min(score, 95), advice)


def _finalize(risks: list, score: int, advice: dict) -> dict:
    if not risks:
        level = "likely_safe"
    elif score >= 45:
        level = "high_risk"
    elif score >= 20:
        level = "medium_risk"
    else:
        level = "low_risk"
    return {"level": level, "score": score, "risks": risks,
            "advice": advice[level], "engine": "local-rules"}


_URL_RE = re.compile(r"(?:https?://|www\.)[^\s\u4e00-\u9fa5，。！？]+", re.I)
_SCHOOL_DOMAIN_HINTS = (".edu.cn", ".edu", "127.0.0.1", "localhost")


def _phishing_risk(text: str) -> list:
    """非学校域名的链接 + 「点击/领取」诱导语 = 典型钓鱼，单独给一条证据"""
    out = []
    for url in _URL_RE.findall(text)[:3]:
        host = re.sub(r"^https?://", "", url).split("/")[0].lower()
        if any(h in host for h in _SCHOOL_DOMAIN_HINTS):
            continue
        if re.search(r"点击|链接|领取|核实|查看|填写", text):
            out.append({"type": "疑似钓鱼链接", "quote": url, "reason":
                        f"链接域名 {host} 不是学校官方域名，且文本里有点击诱导语",
                        "_tier": "high"})
    return out


def analyze_job_chat(chat_text: str) -> dict:
    try:
        d = ask_json(SYS_JSON_ONLY, PROMPT_JOB_RISK + "\n聊天记录：\n" + chat_text)
    except AINotConfigured:
        return _rules_verdict(chat_text, RISK_RULES, JOB_ADVICE)
    if not d.get("level"):
        return _rules_verdict(chat_text, RISK_RULES, JOB_ADVICE)
    d["engine"] = "llm"
    return d


PROMPT_FRAUD_RISK = """你是高校反诈专家。分析下面这段发给学生的美聊/短信/群通知内容，严格按此 JSON 格式输出：
{"level": "high_risk|medium_risk|low_risk|likely_safe", "score": 0到100的欺诈可能性整数, "risks": [{"type": "风险类型", "quote": "原文证据", "reason": "为什么危险"}], "advice": "给学生的行动建议，不超过60字"}
高危特征：索要验证码或账号密码、假冒老师/辅导员收费、诱导私下转账、校园贷裸贷、中奖退税补贴骗局、刷单返利、非学校域名的点击链接。
medium 特征：急着把你引到别的 App 聊、制造紧急感催你交钱、稳赚不赔的投资话术。
risks 只列有原文证据的项，无风险给空数组。"""


def analyze_fraud(text: str) -> dict:
    try:
        d = ask_json(SYS_JSON_ONLY, PROMPT_FRAUD_RISK + "\n待鉴内容：\n" + text)
    except AINotConfigured:
        return _rules_verdict(text, FRAUD_RULES, FRAUD_ADVICE, _phishing_risk(text))
    if not d.get("level"):
        return _rules_verdict(text, FRAUD_RULES, FRAUD_ADVICE, _phishing_risk(text))
    d["engine"] = "llm"
    return d


# 场景自动判定关键词（判不出来按通用鉴诈处理）
SCENE_HINTS = {
    "job": [r"招聘", r"面试", r"\bHR\b", r"兼职", r"实习", r"岗位", r"入职", r"试用期", r"薪资", r"offer", r"岗前"],
    # 「通知排查」只认真正的通知体裁，否则冒充辅导员的私聊会被误标成通知
    "notice": [r"通知", r"公告", r"选课", r"教务"],
}
SCENE_LABELS = {"job": "求职鉴坑", "fraud": "聊天鉴诈", "notice": "通知排查"}


def classify_scene(text: str) -> str:
    for scene, pats in SCENE_HINTS.items():
        if any(re.search(p, text, re.I) for p in pats):
            return scene
    return "fraud"


def scan(text: str, scene: str = "auto") -> dict:
    """安全雷达统一入口：自动分场景 → 求职引擎或反诈引擎 → 带上场景标签返回"""
    scene = scene if scene in SCENE_LABELS else classify_scene(text)
    d = analyze_job_chat(text) if scene == "job" else analyze_fraud(text)
    d["scene"] = scene
    d["scene_label"] = SCENE_LABELS[scene]
    return d


# ---------------------------------------------------------------------
# 六、模块3 延伸：安全雷达的多跳链路（富化 → 命中 → 条款依据）
#     等级和依据都由代码算，大模型只负责把「这条条款为什么适用于这段原文」说成人话，
#     并且只能引用喂给它的条款编号——它自己报的条款号一律丢弃
# ---------------------------------------------------------------------
PROMPT_SCAN_CHAIN = """你是高校安全顾问。结论等级和可引用的条款都已经替你查好了，你只负责把话说清楚。严格按此 JSON 输出：
{"verdict": "一句话结论，不超过34字，必须与给出的等级一致", "links": [{"risk_index": 1, "link": "为什么这条条款适用于这段原文，不超过36字"}], "advice": "给学生的下一步动作，不超过50字"}
硬性规则：
1. links 的 risk_index 只能取给出的编号，条款依据一律用「依据C1」这种编号指代，禁止写出给出清单之外的文件名或条款号；
2. 不许改写、补全法条原文，需要引用时只说编号；
3. 给出的条款清单为空时，verdict 必须写明「暂时找不到可引用的条款依据」，不许硬凑；
4. verdict 不得与给出的判级矛盾，不得把高危说成建议核实了事。
场景：{scene_label}
判级：{level_label}（欺诈可能性 {score}/100）
富化出的事实：{facts}
命中的风险特征（编号｜类型｜原文）：{risks}
可引用的条款（编号｜文件｜条款号）：{clauses}
送检原文：{text}"""

LEVEL_LABEL = {"high_risk": "高危", "medium_risk": "中危", "low_risk": "低危", "likely_safe": "暂未见风险"}


def chain_explain(scene_label: str, level: str, score: int, facts: list,
                  risks: list, clauses: list, text: str) -> tuple:
    """返回 (verdict, {risk_index: link}, advice, engine)；只写字，不改判"""
    fact_text = "；".join(f"{f['kind']}={'、'.join(f['hits'])}" for f in facts) or "无"
    risk_text = "｜".join(f"{i + 1}. {r.get('type', '')}「{(r.get('quote') or '')[:24]}」"
                          for i, r in enumerate(risks)) or "无"
    clause_text = "｜".join(f"C{c['no']}. {c['doc_title']} {c['article_no']}" for c in clauses) or "（空）"
    # 用 replace 而不是 format：Prompt 里的 JSON 示例带花括号
    user = (PROMPT_SCAN_CHAIN
            .replace("{scene_label}", scene_label)
            .replace("{level_label}", LEVEL_LABEL.get(level, level))
            .replace("{score}", str(score))
            .replace("{facts}", fact_text)
            .replace("{risks}", risk_text)
            .replace("{clauses}", clause_text)
            .replace("{text}", text[:600]))
    try:
        d = ask_json(SYS_JSON_ONLY, user)
    except AINotConfigured:
        return _chain_by_rules(level, risks, clauses)
    links = {}
    for x in (d.get("links") or []):
        try:
            idx = int(x.get("risk_index"))
        except (TypeError, ValueError):
            continue
        if 1 <= idx <= len(risks) and str(x.get("link") or "").strip():
            links[idx] = str(x["link"]).strip()
    if not str(d.get("verdict") or "").strip() and not links:
        return _chain_by_rules(level, risks, clauses)
    return (str(d.get("verdict") or "").strip() or _fallback_verdict(level, risks),
            links, str(d.get("advice") or "").strip(), "llm")


def _fallback_verdict(level: str, risks: list) -> str:
    types = "、".join(r.get("type", "") for r in risks[:3] if r.get("type"))
    return (f"{LEVEL_LABEL.get(level, level)}：命中「{types}」" if types
            else f"{LEVEL_LABEL.get(level, level)}：未发现可定性的特征")


def _chain_by_rules(level: str, risks: list, clauses: list) -> tuple:
    """本地规则降级：链路一步不少，只是「连接语」换成模板"""
    links = {}
    for i, r in enumerate(risks, 1):
        nos = r.get("basis") or []
        hit = (r.get("quote") or "").strip()[:20]
        if nos:
            first = next((c for c in clauses if c["no"] == nos[0]), None)
            who = f"{first['doc_title']}{first['article_no']}" if first else f"依据C{nos[0]}"
            links[i] = f"原文「{hit}」属「{r.get('type', '')}」，对应{who}"
        else:
            links[i] = f"原文「{hit}」属「{r.get('type', '')}」，但条款库里还没有对得上的条款"
    verdict = _fallback_verdict(level, risks)
    if not clauses:
        verdict += "（暂无可引用条款依据）"
    return verdict, links, "", "local-rules"


# ---------------------------------------------------------------------
# 七、模块2 延伸：学习清单 → AI 排期规划
#     顺序由后端按图谱前置关系拓扑排好，大模型只负责「解释为什么这么排」，
#     不让它决定顺序，避免幻觉出一个图谱里不存在的依赖
# ---------------------------------------------------------------------
PROMPT_STUDY_PLAN = """你是高校学习规划助手。下面这份学习顺序已经按知识图谱的前置关系拓扑排好，你只负责写理由和整体建议，不许改动顺序、不许新增节点。严格按此 JSON 输出：
{"advice": "给这个学生的整体建议，不超过60字", "reasons": [{"name": "节点名", "reason": "为什么排在这一步，不超过28字"}]}
规则：
1. reasons 必须逐条覆盖给出的每一个 name，名字原样照抄；
2. 理由只能依据给出的前置关系和身份目标，禁止编造文本里没有的课程、证书、比赛；
3. 学生自己加的项，理由里点明「你加入清单的」；系统补齐的项点明「为打通 X 而补」。
身份：{role_label}
目标：{goal}
清单（按学习顺序，含第几周）：{steps}
图谱里的前置关系：{prereqs}"""


def plan_study(steps: list, role_label: str, goal: str) -> tuple:
    """
    steps: [{name, type, week, in_list, prereq: [前置名], needed_by: [后被谁需要]}]
    返回 (advice, {name: reason}, engine)；engine = llm / local-rules
    """
    prereq_text = "；".join(
        f"{s['name']} ← {('、'.join(s['prereq']) or '无前置')}" for s in steps
    )
    step_text = "、".join(f"第{s['week']}周 {s['name']}（{'自己加的' if s['in_list'] else '系统补齐'}）"
                          for s in steps)
    # 用 replace 而不是 format：Prompt 里那段 JSON 示例全是花括号，format 会当成占位符
    user = (PROMPT_STUDY_PLAN
            .replace("{role_label}", role_label)
            .replace("{goal}", goal or "未填写")
            .replace("{steps}", step_text)
            .replace("{prereqs}", prereq_text))
    try:
        d = ask_json(SYS_JSON_ONLY, user)
    except AINotConfigured:
        return _plan_by_rules(steps, role_label, goal)
    reasons = {}
    for r in d.get("reasons", []):
        if isinstance(r, dict) and r.get("name"):
            reasons[r["name"]] = str(r.get("reason", "")).strip()
    if not any(s["name"] in reasons for s in steps):
        return _plan_by_rules(steps, role_label, goal)      # 模型没对上节点名，别硬凑
    return str(d.get("advice", "")).strip(), reasons, "llm"


def _plan_by_rules(steps: list, role_label: str, goal: str) -> tuple:
    """本地规则降级：把拓扑关系直接翻译成人话，不依赖网络"""
    reasons = {}
    for s in steps:
        if not s["in_list"]:
            nb = "、".join(s["needed_by"][:2]) or "后续步骤"
            reasons[s["name"]] = f"清单里没有它，但 {nb} 要用到，先补上"
        elif s["prereq"]:
            reasons[s["name"]] = f"前置是 {'、'.join(s['prereq'][:2])}，啃完才能往上走"
        elif s["type"] == "contest":
            reasons[s["name"]] = f"你锁定的目标（{goal or '赛事'}），按节奏往前推就行"
        else:
            reasons[s["name"]] = "没有前置依赖，随时可以开始"
    mine = [s for s in steps if s["in_list"]]
    auto = [s for s in steps if not s["in_list"]]
    advice = (f"{role_label}：{len(steps)} 步、约 {steps[-1]['week'] if steps else 0} 周。"
              + (f"清单里你只点了 {len(mine)} 项，AI 按前置关系补出 {len(auto)} 项基础；" if auto else
                 f"{len(mine)} 项清单已按前置关系理顺；")
              + (f"从 {steps[0]['name']} 开跑，" if steps else "")
              + "每完成一步点「学完」，计划会跟着往后收。")
    return advice.strip(), reasons, "local-rules"


# ---------------------------------------------------------------------
# 八、模块1 延伸：情报官个性化简报 —— 打分排序在后端算，大模型只写整合导语，
#     只准引用喂给它的通知标题，不许编造没发生的通知
# ---------------------------------------------------------------------
PROMPT_BRIEF_INTRO = """你是高校情报官。下面是根据学生档案从通知库里筛出的高相关通知，请写一段整合导语：把这几条通知当成一个整体说给这个学生听（哪几件跟身份/目标直接相关、有什么时间上的先后关系、建议先看哪条）。严格按此 JSON 输出：
{"intro": "整合导语，不超过110字，直接对学生说话"}
规则：
1. 只能提到下面列表里出现过的通知内容和部门，禁止编造；
2. 结合学生身份和目标说「为什么跟你有关」，不要罗列标题原文；
3. 语言像学长在耳边提醒，不用客套开场白。
学生档案：{profile}
入选通知（按相关度排序）：{notices}"""


def brief_intro(profile_text: str, notice_lines: list) -> dict:
    """notice_lines: ["《标题》（部门，日期）", ...] → {"intro", "engine"}；没配 Key 时本地模板降级"""
    if not notice_lines:
        return {"intro": "通知库里暂时没有可整合的内容，先点「拉取最新」抓一轮官方通知。",
                "engine": "local-rules"}
    user = (PROMPT_BRIEF_INTRO
            .replace("{profile}", profile_text or "未填写（按普通在校生处理）")
            .replace("{notices}", "\n".join(notice_lines)))
    try:
        d = ask_json(SYS_JSON_ONLY, user)
    except AINotConfigured:
        pass
    else:
        intro = str(d.get("intro") or "").strip()
        if intro:
            return {"intro": intro[:130], "engine": "llm"}
    # 本地降级：不假装会写文章，就用可核实的结构化句式
    head = notice_lines[0]
    tail = "、".join(l.split("《")[1].split("》")[0] for l in notice_lines[1:3])
    extra = f"另外{tail}也值得留意。" if tail else ""
    return {"intro": f"近段时间最值得你先看的是{head}。{extra}完善个人档案后，筛选会更贴合你的身份和目标。",
            "engine": "local-rules"}
