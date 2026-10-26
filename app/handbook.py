"""安全雷达的「有理有据」三步：实体富化（hop1）→ 条款匹配（hop3）→ 置信度与弃权。

检索刻意做成**字面匹配**（关键词 + 条款号），不引向量库：条款库总共几十条，
命中理由必须能被人工复核——「原文出现『押金』，而劳动合同法第九条的 keywords 里有押金」
这种解释评委和学生都听得懂，向量相似度分数谁也说不清。

三条硬规矩（照 safetrace 的证据工程做法）：
1. 只有 verified=1 且 enabled=1 的条款才可能被引用；
2. 找不到对得上的条款就明说「条款库未覆盖」，绝不许大模型自己编条款号；
3. 置信度只由硬指标算（命中强度 / 佐证条数 / 条款可信度均值），不由模型自评。
"""
import re

# 送检内容里的「事实」：这些是富化层要抠出来的东西，也是条款 keywords 的对齐对象
FACT_PATTERNS = [
    ("收费名目", r"(押金|保证金|培训费|服装费|材料费|资料费|体检费|建档费|会费|内推费|手续费|工服费|报名费|班费|书本费|代办费)"),
    ("金额", r"(?:[¥￥]\s?\d[\d,.]*|\d[\d,.]*\s?(?:元|块|万))"),
    ("收款方式", r"(微信|支付宝|银行卡|对公账户|收款码|转账|汇款|打款)"),
    ("证件材料", r"(身份证|学生证|护照|学位证|毕业证|户口本|学信网)"),
    ("验证码账号", r"(验证码|动态密码|支付密码|账号密码|CVV|短信码)"),
    ("链接入口", r"(?:https?://|www\.)[^\s\u4e00-\u9fa5，。！？]+"),
    ("时限施压", r"(立刻|马上|尽快|赶紧|今天内|24小时|限时|过时作废|今天必须)"),
    ("对方自称", r"(辅导员|班主任|老师|教务处|学生处|HR|人事|公安|检察院|法院|客服|学长|学姐)"),
    ("账号出借", r"((租[用]?|借[用]?|收购|买卖|收)[^\n]{0,6}(银行卡|电话卡|手机卡|微信|qq|账号|二维码|信用卡)"
                 r"|(银行卡|电话卡|手机卡|微信|账号|信用卡)[^\n]{0,8}(租|借|卖|走流水))"),
    ("刷单任务", r"(刷单|刷销量|做任务|垫[资付]|返利|好评|点赞单)"),
    ("贷款分期", r"(贷款|分期|额度|放款|免息|校园贷|套现)"),
    ("不签协议", r"(不用?[签立]合同|没有合同|无需协议|口头约定|试岗)"),
]

_SCENE_BASE = 6          # 场景对得上才计分（all 场景的通用条款也给分）
_RISK_BONUS = 30         # 条款标了同一风险类型，是最强信号
_KW_WEIGHT = 7           # 每个命中的关键词按长度加权计分
_TRUST_FLOOR = 78

# 来源层级：法律条文比校方手册硬，展示时也要让学生看清手里这条是什么级别
SOURCE_LABEL = {"law": "国家法律", "regulation": "部委规章/规范性文件",
                "judicial": "两高司法文件", "school": "校方手册/校规"}


def enrich(text: str) -> list:
    """hop1 事实富化：把「对方要钱/要证件/要验证码/给链接/催时间」这些事实先抠出来"""
    facts = []
    for kind, pat in FACT_PATTERNS:
        hits = []
        for m in re.finditer(pat, text, re.I):
            v = m.group(0).strip()
            if v and v not in hits:
                hits.append(v)
        if hits:
            facts.append({"kind": kind, "hits": hits[:4]})
    return facts


def _kw_score(keywords: str, text: str, risk_type: str) -> tuple:
    """条款 keywords 逐个在原文/风险类型里找，命中的按字数加权；同时返回命中的词。
    第二种命中要求「关键词整个出现在风险类型名里」（如「验证码」∈「索要验证码/账号密码」），
    不做前两字模糊匹配——展示给学生的命中理由必须能一眼复核。"""
    got, score = [], 0.0
    low_text = text.lower()
    for kw in [k.strip() for k in keywords.split(",") if k.strip()]:
        if kw.lower() in low_text:
            score += min(14, _KW_WEIGHT * len(kw))
            got.append(kw)
        elif risk_type and kw in risk_type:
            score += _KW_WEIGHT
            got.append(kw)
    return got, score


def match_clauses(lib: list, scene: str, risk_type: str, text: str, limit: int = 2) -> list:
    """hop3 条款匹配：场景相符的条款里按分数取前 limit 条（lib 已由调用方过滤成可引用的）"""
    scored = []
    for c in lib:
        if c["scene"] not in (scene, "all"):
            continue
        got, s = _kw_score(c["keywords"], text, risk_type or "")
        type_hit = bool(risk_type) and risk_type in (c["risk_type"] or "")
        if not got and not type_hit:      # 原文一个词没命中、风险类型也对不上 → 只是「场景像」，不算依据
            continue
        if type_hit:
            s += _RISK_BONUS
        s += _SCENE_BASE + max(0.0, (int(c["trust"]) - _TRUST_FLOOR) / 10.0)
        scored.append((round(s, 1), got, c))
    scored.sort(key=lambda x: (-x[0], x[2]["id"]))
    return [{"no": 0, "clause": c, "score": s, "matched": g} for s, g, c in scored[:limit]]


def confidence(hits: list) -> dict:
    """置信度只由三个硬指标合成：最强一条的命中强度、佐证条款数量、条款平均可信度。
    入参用 cover() 出来的已编号条款列表——由模型自评「我有几分把握」是没有意义的。"""
    if not hits:
        return {"value": None, "why": [], "note": "条款库里没有对得上的条款，不给出依据"}
    best = max(h["score"] for h in hits)
    strength = min(1.0, best / 55.0)
    breadth = min(1.0, 0.45 + 0.28 * (len(hits) - 1))
    avg_trust = sum(int(h["trust"]) for h in hits) / len(hits) / 100.0
    value = round(100 * (0.5 * strength + 0.2 * breadth + 0.3 * avg_trust))
    return {"value": value,
            "why": [f"最强一条依据命中强度 {best}（折算 {round(strength * 100)}%）",
                    f"可互相印证的依据 {len(hits)} 条",
                    f"条款可信度均值 {round(avg_trust * 100)} 分"],
            "note": ""}


def cover(scene: str, risks: list, text: str, lib: list, per_risk: int = 2) -> tuple:
    """给每条风险配依据；配不上的如实标 missing（unknown ≠ safe，不能因为没依据就判安全）"""
    cited, missing, index = [], [], {}
    for i, r in enumerate(risks):
        hits = match_clauses(lib, scene, r.get("type", ""), r.get("quote") or text, per_risk)
        if not hits:
            missing.append({"risk_index": i + 1, "type": r.get("type", "")})
            r["basis"] = []
            continue
        nos = []
        for h in hits:
            c = h["clause"]
            key = (c["doc_title"], c["article_no"])
            if key not in index:                     # 同一条款被多条风险引用时只占一个编号
                index[key] = len(cited) + 1
                cited.append({"no": index[key], "doc_title": c["doc_title"], "doc_year": c["doc_year"],
                              "article_no": c["article_no"], "title": c["title"], "text": c["text"],
                              "source": c["source"], "source_label": SOURCE_LABEL.get(c["source"], c["source"]),
                              "trust": int(c["trust"]), "url": c["url"],
                              "matched": h["matched"], "score": h["score"], "note": c["note"] or ""})
            nos.append(index[key])
        r["basis"] = nos
    return cited, missing
