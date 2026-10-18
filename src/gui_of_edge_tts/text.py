"""文本与合成参数处理（不依赖界面）。"""

import math
import re
from collections import Counter

from .lang import L

# edge-tts 的上游限制：单次请求的 SSML 正文按字节切分，切分长度 4096 字节。
# 长文本上游会自己切，但界面要在**开始生成之前**就告诉用户"这句有多长"。
MAX_REQUEST_BYTES = 4096

# 中文全角标点 → 英文半角。上游服务对全角标点的断句质量明显更差。
_PUNCTUATION_MAP = str.maketrans(
    {
        "。": ".",
        "？": "?",
        "！": "!",
        "，": ",",
        "；": ";",
        "：": ":",
        "、": ",",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "《": "<",
        "》": ">",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "—": "-",
        "…": "...",
    }
)

# 上游明确不支持的字符区间（垂直制表符、控制字符等），会被替换成空格。
_INCOMPATIBLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def preprocess_text(text: str) -> str:
    """把用户输入整理成上游能接受的文本。

    只做三件事：统一标点、去掉不可见控制字符、去掉首尾空白。
    **不做**改写、不做截断——用户写什么就说什么。
    """
    if not text:
        return ""
    text = _INCOMPATIBLE.sub(" ", text)
    text = text.translate(_PUNCTUATION_MAP)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 连续 3 个以上换行压成 2 个：段落之间留一空行即可，多余的空行会让
    # 上游产生一长段静音。
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def count_words(text: str) -> int:
    """数"会被读出来的词"。

    英文按词计数（``don't`` 算一个词，连字符同理）；中文没有空格，按字符数
    估算（一个汉字算一个词）；剩下的标点等可见字符也算一个（它们会被读出来）。
    SRT 合并规则用它来决定一个字幕块能放几个词。
    """
    if not text:
        return 0
    cjk = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z0-9\u00c0-\u024f]+(?:['’-][A-Za-z0-9]+)*", text))
    # 撇号与连字符已经算进 latin 里了，这里要排除掉，否则 "don't" 会数成 3
    other = len(
        re.findall(r"[^\sA-Za-z0-9\u00c0-\u024f\u3400-\u4dbf\u4e00-\u9fff'’\-]", text)
    )
    return cjk + latin + other


def language_of(text: str) -> str:
    """判断这段文字主要是什么语言：``"zh"`` / ``"en"`` / ``"mixed"`` / ``""``。

    **为什么要判**：字数和时长的算法中英完全不同——
    中文按**汉字数**（一个字≈一个音节），英文按**词数**。
    用一套算法去量两种文字，总有一种是错的：英文按字符数会虚高两三倍
    （"engineering" 是一个词 11 个字符），中文按词数又会数不出东西
    （没有空格，整段算一个"词"）。
    """
    if not text.strip():
        return ""
    cjk = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z\u00c0-\u024f]+", text))
    if cjk == 0 and latin == 0:
        return ""
    # 中文标点也是"这是中文"的证据：`。，、！？；：（）` 在拉丁文本里不出现。
    has_cjk_punctuation = bool(re.search(r"[\u3000-\u303f\uff00-\uffef]", text))
    if cjk and cjk >= latin:
        return "zh"
    if cjk:
        # 有汉字、但拉丁更多：**中英混排**，按中文算（中文要逐字数，
        # 英文按词补进去）。
        return "zh"
    if has_cjk_punctuation:
        # 没有汉字，但写了中文标点（"hello。"）：这是中文语境，
        # **不能**因为拉丁字母占多数就判成英文。
        return "zh"
    if latin:
        return "en"
    return "mixed"


# --------------------------------------------------------------------------- #
# 默认文件名：轻量的"提取式标题"
#
# 用户 2026-10-17 的需求：粘贴内容后点生成，不要再每次都手打文件名；
# 希望程序根据内容给一个**和内容强相关**的默认名，同时保留重命名权。
#
# 三条约束决定了这里的做法：
#   1. **不联网、不加载模型**——不能为了文件名把 exe 变大、或让离线不可用；
#   2. **纯函数、可测试**——UI 只负责把结果放进 `initialfile`；
#   3. **快**——大段文字也只扫前 `TITLE_SCAN_CHARS` 个字符。
#
# 算法是"提取"而不是"生成"：中文取首句（去掉称谓/日期/导语），
# 英文取专有名词 + 高频内容短语。结果不完美，但用户可以改；
# 比"前 40 个字符"强得多，而且没有新增依赖。
# --------------------------------------------------------------------------- #

#: 生成标题时最多扫前面多少个字符（大段文字也不拖慢点击"生成"）。
TITLE_SCAN_CHARS = 6000
#: 默认文件名里中文标题最多保留多少个字符。
TITLE_MAX_CJK = 24
#: 默认文件名里英文标题最多保留多少个字符。
TITLE_MAX_LATIN = 60

_CJK = r"\u3400-\u4dbf\u4e00-\u9fff"
_CJK_RUN = re.compile(f"[{_CJK}]+")
_CJK_DATE = re.compile(
    r"(?:\d{4}年)?\d{1,2}月\d{1,2}日|(?:周|星期)[一二三四五六日天]|\d{4}年"
)
#: 中文导语/称谓：出现在开头时去掉，不进入文件名。
_CJK_LEAD = re.compile(
    r"^(?:据[^，,。]{0,12}(?:报道|消息|电)|据悉|据报道|据新华社|据央视|记者|近日|日前|"
    r"昨日|昨天|今天|当地时间|消息|我们|本文|文章|国家主席|国务院总理|中共中央总书记|"
    r"副总统|总统|总理|首相|主席|部长|发言人|教授|博士|先生|女士|委员长|总书记|"
    r"此外|同时|因此|然而|不过|所以|这意味着|换句话说|总之|综上|"
    r"近年来|随着|目前|如今|当下|长期以来|一段时间以来|"
    r"专家认为|有专家认为|分析人士认为|业内人士认为|很多人以为|不少人认为|"
    r"有人认为)[\s，,：:、]*"
)
#: "××表示/指出/称……" 只留主语。
_CJK_TRAIL = re.compile(
    r"(?:表示|指出|称|说|宣布|介绍|强调|认为|透露|告诉记者|在讲话中|在接受采访时).*$"
)
#: 中文关键词提取时排除的虚词（只用来挑"实词"二字词）。
_CJK_STOP_CHARS = set(
    "的了和与及在是为对将已正有这那其也就都而并且但如果因为所以可以"
    "我们你们他们她们它们一个一些进行通过对于关于以及等被把从向于"
)

_EN_STOP = frozenset(
    """a an the and or but if then than that this these those there here
    is are was were be been being am do does did doing have has had having
    i you he she it we they me him her us them my your his its our their
    of in on at to for from by with without about into over after before under
    as so such not no nor can could may might must shall should will would
    just also very more most much many some any all each every other another
    one two three first second new said says say told tell according
    president vice prime minister secretary chairman chairwoman senator
    governor mayor mr mrs ms dr prof general king queen prince princess
    monday tuesday wednesday thursday friday saturday sunday
    january february march april may june july august september october
    november december
    article articles video videos paper papers blog post content text
    recent recently year years today now currently increasingly
    faster cheaper previous real question whether
    how what why when where who which
    """.split()
)
#: 常见动词：文件名里通常是"谁 + 什么"，动词只会占字数。
_EN_VERBS = frozenset(
    """arrived arrive arrives came come comes coming went go goes gone going
    gonna made make makes making added add adds announced announce announces
    told tell tells told held hold holds holding launched launch launches
    signed sign signs called call calls calling became become becomes becoming
    including include includes met meet meets build builds building built
    plan plans planning buy buys sell sells open opens start starts
    create creates created develop develops developed release releases released
    talk talks talking help helps helping replace replaces replaced replacing
    change changes changed changing spread spreads spreading
    """.split()
)
_EN_WORD = re.compile(
    r"\d+[A-Za-z][A-Za-z0-9]*(?:['’\-][A-Za-z0-9]+)*|"
    r"[$€£¥]?\d+(?:[.,]\d+)*%?|"
    r"[A-Za-z\u00c0-\u024f][A-Za-z\u00c0-\u024f0-9]*(?:['’\-][A-Za-z\u00c0-\u024f0-9]+)*"
)
_EN_PROPER_CONNECTORS = frozenset({"of", "the", "de", "van", "von", "del", "da", "bin", "al"})


def _title_source(text: str) -> str:
    """标题分析用的正文：去 URL/邮箱/Markdown 标记，并截到扫描上限。"""
    cleaned = re.sub(r"https?://\S+|www\.\S+", " ", text)
    cleaned = re.sub(r"\S+@\S+", " ", cleaned)
    cleaned = re.sub(r"[*_#>`~]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:TITLE_SCAN_CHARS]


def _sentences(text: str) -> list:
    """切句：**小数点和缩写里的点不算句号**。

    旧写法 `(?<=[.!?])\\s*` 连"5.4%"里的点都当句末——用户看到标题从
    "5.4% year on year"变成"4% year on year"，就是这里把 "5." 切掉了。
    现在：`.`/`!`/`?` 后面必须跟空白或文本结束才断句；中文 `。！？` 照常断。
    """
    return [
        part.strip()
        for part in re.split(r"(?<=[。！？])|(?<=[.!?])(?=\s|$)|\n+", text)
        if part.strip()
    ]


def _cjk_count(text: str) -> int:
    """汉字个数（不是"连续汉字段数"）。"""
    return sum(len(run) for run in _CJK_RUN.findall(text))


def _focus_terms(sentence: str, language: str) -> list:
    """句子相似度用的词袋：英文实词 / 中文二字词。"""
    if language == "en":
        words = [word.lower().strip(".") for word in _EN_WORD.findall(sentence)]
        return [
            word
            for word in words
            if word not in _EN_STOP
            and word not in _EN_VERBS
            and len(word) >= 2
        ]
    terms: list = []
    for run in _CJK_RUN.findall(sentence):
        for index in range(len(run) - 1):
            pair = run[index:index + 2]
            if pair[0] in _CJK_STOP_CHARS or pair[1] in _CJK_STOP_CHARS:
                continue
            terms.append(pair)
    return terms


def _textrank_scores(terms_by_sentence: list) -> list:
    """轻量 TextRank：句子是节点，词袋重合度是边权。

    论文里的完整实现要建图 + 迭代 30 次；这里句子数很少（最多 60），
    直接算 O(n²) 相似度矩阵即可。它比"关键词个数 / 句长"稳定得多：
    不会被一句堆满实词的背景句骗走，也不会总选第一句。
    """
    count = len(terms_by_sentence)
    if count == 0:
        return []
    sets = [set(terms) for terms in terms_by_sentence]
    similarity = [[0.0] * count for _ in range(count)]
    for left in range(count):
        for right in range(count):
            if left == right or not sets[left] or not sets[right]:
                continue
            shared = len(sets[left] & sets[right])
            if shared:
                similarity[left][right] = shared / (
                    math.log(len(terms_by_sentence[left]) + 1)
                    + math.log(len(terms_by_sentence[right]) + 1)
                    + 1
                )

    scores = [1.0] * count
    for _ in range(30):
        updated: list = []
        for index in range(count):
            total = 0.15
            for other in range(count):
                if not similarity[other][index]:
                    continue
                weight = sum(similarity[other]) or 1.0
                total += 0.85 * scores[other] * similarity[other][index] / weight
            updated.append(total)
        scores = updated
    return scores


def _pick_focus(sentences: list, language: str) -> int:
    """返回最适合当标题的句子下标（TextRank + 位置/背景/观点修正）。"""
    limited = sentences[:60]
    if len(limited) <= 1:
        return 0
    terms = [_focus_terms(sentence, language) for sentence in limited]
    scores = _textrank_scores(terms)
    if not scores:
        return 0
    for index, sentence in enumerate(limited):
        # 轻位置先验：新闻首句通常就是导语；只加 0.05，不影响中心句胜出。
        if index == 0:
            scores[index] += 0.05
        # 长文开头常是背景，不是主旨；观点句再补一点。
        if re.match(
            r"^(?:in recent years|recently|over the past|nowadays|today|for years|"
            r"in today's|these days|近年来|随着|目前|如今|当下|长期以来|一段时间以来)",
            sentence,
            re.IGNORECASE,
        ):
            scores[index] -= 0.2
        if re.search(
            r"\b(?:real question|key point|the point|in fact|actually|important|"
            r"means|suggests|however)\b",
            sentence,
            re.IGNORECASE,
        ) or re.search(
            r"(?:真正|关键|核心|本质|意味着|重要的是|结论是|因此|所以|认为|指出|强调)",
            sentence,
        ):
            scores[index] += 0.1
    return max(range(len(limited)), key=lambda index: scores[index])


def _best_cjk_sentence(text: str, sentences: list) -> tuple:
    """中文中心句：TextRank 选句，返回 ``(句子, 下标)``。"""
    index = _pick_focus(sentences, "zh")
    if not sentences:
        return text, 0
    return sentences[index], index


def _cjk_title(text: str, limit: int, fallback_text: str = "") -> str:
    """中文标题：从**选中的中心句**里取首小句（去导语/称谓/日期）。"""
    work = _CJK_DATE.sub("", text)
    for _ in range(4):
        stripped = _CJK_LEAD.sub("", work, count=1)
        if stripped == work:
            break
        work = stripped
    clauses = [
        _CJK_TRAIL.sub("", clause).strip()
        for clause in re.split(r"[，,；;：:、。！？!?]", work)
    ]
    clauses = [clause for clause in clauses if clause]
    if not clauses:
        return _cjk_keywords(fallback_text or text, limit)
    title = clauses[0]
    index = 1
    while _cjk_count(title) < 6 and index < len(clauses):
        title += clauses[index]
        index += 1
    # 文件名不要标点（中文标点在 Windows 文件名里能用，但看起来脏）
    title = re.sub(rf"[^{_CJK}A-Za-z0-9]+", "", title)
    title = title[:limit].strip("的了和与及在是为对将已正有")
    if _cjk_count(title) < 2:
        return _cjk_keywords(fallback_text or text, limit)
    return title


def _cjk_keywords(text: str, limit: int) -> str:
    """中文兜底：高频二字词（不重叠），用 ``·`` 连接。"""
    counts: Counter = Counter()
    first: dict = {}
    for run in _CJK_RUN.findall(text):
        for index in range(len(run) - 1):
            pair = run[index:index + 2]
            if pair[0] in _CJK_STOP_CHARS or pair[1] in _CJK_STOP_CHARS:
                continue
            counts[pair] += 1
            first.setdefault(pair, index)
    candidates = [pair for pair, count in counts.items() if count >= 2]
    candidates.sort(key=lambda pair: (-counts[pair], first[pair]))
    chosen: list = []
    for pair in candidates:
        if any(set(pair) & set(existing) for existing in chosen):
            continue
        chosen.append(pair)
        if len("".join(chosen)) >= limit:
            break
    if chosen:
        return "·".join(chosen)[:limit]
    first_run = _CJK_RUN.search(text)
    return first_run.group(0)[:limit] if first_run else ""


def _is_cap(word: str) -> bool:
    return bool(word) and (word[0].isupper() or word.isupper())


def _phrase_word_ok(word: str) -> bool:
    low = word.lower().strip(".")
    if low in _EN_STOP or low in _EN_VERBS:
        return False
    return len(low) >= 2


def _proper_phrases(tokens: list) -> list:
    """连续大写词组成的专有名词短语（``Xi Jinping`` / ``United States``）。"""
    phrases: list = []
    index = 0
    while index < len(tokens):
        word = tokens[index]
        if not _is_cap(word) or not _phrase_word_ok(word):
            index += 1
            continue
        start = index
        parts = [word]
        index += 1
        while index < len(tokens):
            nxt = tokens[index]
            if _is_cap(nxt) and _phrase_word_ok(nxt):
                parts.append(nxt)
                index += 1
                continue
            if (
                nxt.lower() in _EN_PROPER_CONNECTORS
                and index + 1 < len(tokens)
                and _is_cap(tokens[index + 1])
                and _phrase_word_ok(tokens[index + 1])
            ):
                parts.extend((nxt, tokens[index + 1]))
                index += 2
                continue
            break
        phrase = " ".join(parts)
        if phrase.lower() not in _EN_STOP:
            phrases.append((phrase, start))
    # 大小写不重复；"United States" 在时不要再塞一个 "US"
    seen: set = set()
    unique: list = []
    joined = " ".join(phrase.lower() for phrase, _pos in phrases)
    for phrase, position in phrases:
        key = phrase.lower()
        if key in seen:
            continue
        if key in {"us", "u.s.", "u.s.a.", "usa"} and "united states" in joined:
            continue
        seen.add(key)
        unique.append((phrase, position))
    return unique


_EN_TRAILING = frozenset(
    """a an the of in on at to for from by with and or but as that this
    these those is are was were be been being over under above below around
    through across into onto off up down out about than so such very more most
    much many some any all each every other another one two three first second""".split()
)
_EN_LEAD_META = re.compile(
    r"^(?:in this (?:article|video|paper)[,:]?\s*|"
    r"we (?:are going to|will|want to) (?:talk|discuss|look) (?:about|at)\s+|"
    r"this (?:article|video|paper) (?:is about|discusses|explains)\s+|"
    r"the topic is\s+|today,? we\s+|in recent years,?\s*|recently,?\s+)",
    re.IGNORECASE,
)
_EN_TRAIL_META = re.compile(
    r"[,;:\s]+(?:in this (?:article|video|paper)|for (?:now|example))\.?$",
    re.IGNORECASE,
)
_EN_WEEKDAYS = frozenset(
    "monday tuesday wednesday thursday friday saturday sunday".split()
)


def _sentence_title_candidate(words: list, limit: int) -> str:
    """把一个词序列整理成标题候选；不合格返回空串。"""
    words = list(words)
    # 标题不必带"星期几"这类时效信息："arrived ... on Wednesday" → 去掉
    if (
        len(words) >= 3
        and words[-1].lower().strip(".") in _EN_WEEKDAYS
        and words[-2].lower().strip(".") == "on"
    ):
        words = words[:-2]
    while words and words[-1].lower().strip(".") in _EN_TRAILING:
        words.pop()
    if len(words) < 2:
        return ""
    lowered = " ".join(word.lower().strip(".") for word in words)
    if re.match(
        r"^(?:the real question|the question|whether|how|what|why|when|where|"
        r"who|in recent years|recently|today|this article|we|i)\b",
        lowered,
    ):
        return ""
    if words[0].lower().strip(".") in _EN_VERBS:
        return ""
    if sum(1 for word in words if word.lower().strip(".") not in _EN_STOP) < 2:
        return ""
    title = " ".join(words).strip(" .,:;!?\"'“”‘’()[]")
    while len(title) > limit and len(words) > 2:
        words.pop()
        title = " ".join(words).strip(" .,:;!?\"'“”‘’()[]")
    while words and words[-1].lower().strip(".") in _EN_TRAILING:
        words.pop()
        title = " ".join(words).strip(" .,:;!?\"'“”‘’()[]")
    # 先去掉悬空介词后，句尾才可能露出 "on Wednesday"
    if (
        len(words) >= 3
        and words[-1].lower().strip(".") in _EN_WEEKDAYS
        and words[-2].lower().strip(".") == "on"
    ):
        words = words[:-2]
        title = " ".join(words).strip(" .,:;!?\"'“”‘’()[]")
    if not title:
        return ""
    return title[0].upper() + title[1:]


def _english_sentence_title(sentence: str, limit: int) -> str:
    """把中心句裁成**一句完整的话/一个完整小句**，不随便从中间截词。

    英文里"名词堆叠"最容易读起来不像人话（例如
    "OpenAI San Francisco Model Agents"）。完整句子至少语法是对的；
    优先级：

    1. 整句不太长 → 用整句（去导语）；
    2. 整句太长 → 先用**第一个逗号/分号/冒号前的小句**；
    3. 还没有 → 最多 9 个词，并去掉句尾悬空的介词/冠词。

    数字（5.4%、$348）在 `_EN_WORD` 里是**一个 token**，不会被截成
    "5." 和 "4%"（用户实测标题变成 "4% year on year" 的那个 bug）。
    """
    text = (sentence or "").strip()
    for _ in range(2):
        stripped = _EN_LEAD_META.sub("", text, count=1)
        if stripped == text:
            break
        text = stripped
    text = _EN_TRAIL_META.sub("", text).strip()
    all_words = _EN_WORD.findall(text)
    if len(all_words) < 2:
        return ""

    candidates: list = []
    full = " ".join(all_words)
    if 2 <= len(all_words) <= 14 and len(full) <= limit:
        candidates.append(all_words)

    clause_text = re.split(r"[,;:—–](?=\s|$)", text, maxsplit=1)[0]
    clause_words = _EN_WORD.findall(clause_text)
    if (
        clause_words != all_words
        and 3 <= len(clause_words) <= 14
        and len(" ".join(clause_words)) <= limit
    ):
        candidates.append(clause_words)

    candidates.append(all_words[:9])
    for words in candidates:
        title = _sentence_title_candidate(words, limit)
        if title:
            return title
    return ""


def _natural_keyword_title(
    proper: list, top_bigram, top_words: list, limit: int
) -> str:
    """中心句不能直接当标题时的兜底：**两个名词用 and 连起来**。

    比"名词 + 动词 + 名词"的堆叠自然得多：
    ``AI and Teachers`` / ``Artificial Intelligence and Education``。
    """
    units: list = []
    for phrase, _pos in proper[:2]:
        if phrase.lower() not in _EN_STOP:
            units.append(phrase)
    if top_bigram is not None:
        units.append(top_bigram[0])
    for word, _position in top_words:
        if word.lower().strip(".") in _EN_VERBS:
            continue
        units.append(word.capitalize())
    unique: list = []
    seen: set = set()
    for unit in units:
        key = unit.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(unit)
    if not unique:
        return ""
    if len(unique) >= 2:
        title = f"{unique[0]} and {unique[1]}"
    else:
        title = unique[0]
    return title[:limit].strip(" .,:;!?\"'“”‘’()[]")


def _latin_title(text: str, limit: int) -> str:
    """英文标题：**先挑最能代表主旨的句子**，再从里面取专有名词 + 高频短语。

    旧版永远拿前两句；长文里中心句常在第三、第四句，于是标题只像个开头。
    现在给每句按"关键词命中 + 专有名词 + 位置"打分，选中句后再提取标题。
    """
    sentences = _sentences(text) or [text]
    whole_tokens = _EN_WORD.findall(text)
    if not whole_tokens:
        return ""

    global_proper = _proper_phrases(whole_tokens)
    proper_words = {
        word.lower() for phrase, _pos in global_proper for word in phrase.split()
    }

    counts: Counter = Counter()
    first: dict = {}
    for index, token in enumerate(whole_tokens):
        low = token.lower().strip(".")
        if (
            low in _EN_STOP
            or low in _EN_VERBS
            or low in proper_words
            or len(low) < 3
        ):
            continue
        counts[low] += 1
        first.setdefault(low, index)

    bigrams: Counter = Counter()
    bigram_first: dict = {}
    for index in range(len(whole_tokens) - 1):
        left = whole_tokens[index].lower().strip(".")
        right = whole_tokens[index + 1].lower().strip(".")
        if (
            left in _EN_STOP
            or right in _EN_STOP
            or left in _EN_VERBS
            or right in _EN_VERBS
            or left in proper_words
            or right in proper_words
            or len(left) < 3
            or len(right) < 3
        ):
            continue
        pair = (left, right)
        bigrams[pair] += 1
        bigram_first.setdefault(pair, index)

    # ---- 选中心句（TextRank，不再"永远取前两句"）-------------------------
    focus = sentences[_pick_focus(sentences, "en")]

    # 首选：把中心句裁成一句短而完整的话（语法天然成立）
    sentence_title = _english_sentence_title(focus, limit)
    if sentence_title:
        return sentence_title

    focus_tokens = _EN_WORD.findall(focus)
    focus_words = {word.lower().strip(".") for word in focus_tokens}
    proper = _proper_phrases(focus_tokens) or global_proper[:2]

    # 高频短语：优先选中心句里出现过的
    focus_pairs = set(zip(
        [word.lower().strip(".") for word in focus_tokens],
        [word.lower().strip(".") for word in focus_tokens[1:]],
    ))
    top_bigram = None
    candidates = (
        [(pair, count) for pair, count in bigrams.items() if pair in focus_pairs]
        or list(bigrams.items())
    )
    if candidates:
        pair, count = max(
            candidates,
            key=lambda item: (item[1] * 2, -bigram_first[item[0]]),
        )
        if count >= 2 or pair in focus_pairs:
            top_bigram = (" ".join(word.capitalize() for word in pair), 0)

    top_words = [
        (word, position)
        for word, position in sorted(
            first.items(),
            key=lambda item: (
                0 if item[0] in focus_words else 1,
                -counts[item[0]],
                item[1],
            ),
        )[:4]
    ]

    # 句子不能直接当标题（疑问/背景/导语）时，用两个名词 + and 兜底。
    fallback = _natural_keyword_title(proper, top_bigram, top_words, limit)
    if fallback:
        return fallback

    # 最后兜底：中心句按词边界截断
    title = ""
    for word in focus.split():
        candidate = f"{title} {word}".strip()
        if len(candidate) > limit:
            break
        title = candidate
    return title.strip(" .,:;!?\"'“”‘’()[]")


def _fallback_title(source: str, limit: int) -> str:
    """非中英文字（日文/韩文/俄文……）的兜底：首句去掉标点后截断。"""
    sentences = _sentences(source)
    first = sentences[0] if sentences else source
    first = re.sub(
        r"[^\w\u3400-\u4dbf\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]+",
        " ",
        first,
    )
    return re.sub(r"\s+", " ", first).strip()[:limit].strip()


def suggest_title(text: str) -> str:
    """从正文里提取一个**与内容强相关**的短标题（不联网、不用模型）。

    这是"提取式"而不是"生成式"：
      * 先用轻量 TextRank 选出**最能代表全文的句子**（不是永远取首句）；
      * 中文：从中心句取首小句，去掉导语/称谓/日期，过长时截断；
      * 英文：专有名词（人名/地名）+ 高频内容短语，按原文顺序拼接；
      * 其他文字：首句去标点后截断。

    结果只是**保存对话框里的默认文件名**，用户仍然可以随意改。
    """
    source = _title_source(text or "")
    if not source:
        return ""
    # 日文假名/韩文不能走中文路径（"首句去标点"会把假名整个删掉）。
    if re.search(r"[\u3040-\u30ff\uac00-\ud7af]", source):
        return _fallback_title(source, TITLE_MAX_CJK)
    if language_of(source) == "en":
        title = _latin_title(source, TITLE_MAX_LATIN)
    else:
        sentences = _sentences(source)
        focus, _index = _best_cjk_sentence(source, sentences)
        title = _cjk_title(focus, TITLE_MAX_CJK, fallback_text=source)
    return (title or _fallback_title(source, TITLE_MAX_CJK)).strip()


_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)


def suggest_filename(text: str, extension: str = ".mp3") -> str:
    """标题 → **安全的默认文件名**；提取不出来时返回空串（由调用方兜底）。"""
    title = suggest_title(text)
    if not title:
        return ""
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", title)
    # 标点变空格，但**小数点要留着**：5.4% 不能变成 "5 4%"。
    stem = re.sub(r"[，,。;；:：!！?？、]+", " ", stem)
    stem = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" .")
    if not stem:
        return ""
    if stem.lower() in _WINDOWS_RESERVED:
        stem = f"_{stem}"
    return f"{stem[:80].strip(' .')}{extension}"


def add_filename_suffix(name: str, suffix: str) -> str:
    """在扩展名前插入参数后缀；``suffix`` 已由调用方保证以 ``_`` 开头。"""
    if not name or not suffix:
        return name
    stem, dot, ext = name.rpartition(".")
    if dot and ext and len(ext) <= 5:
        return f"{stem}{suffix}.{ext}"
    return f"{name}{suffix}"


#: 中文语速（汉字/分钟）。Edge-TTS 晓晓一类中文语音的常见节奏。
SPEECH_CJK_PER_MINUTE = 240.0
#: 英文语速（词/分钟）。Edge-TTS Brian/Aria 一类英文语音的常见节奏。
#: 比读得快一点点，因为 Azure 的默认语速偏轻快。
SPEECH_LATIN_PER_MINUTE = 165.0


def estimate_seconds(text: str) -> float:
    """按语言分别估算朗读时长（秒）。

    中文按汉字数、英文按词数，各自用自己的语速——**这是两套算法，
    不是一个公式换系数**，因为"一个单位该数什么"本身就不同。
    """
    if not text.strip():
        return 0.0
    language = language_of(text)
    if language == "en":
        rate = SPEECH_LATIN_PER_MINUTE
        units = len(re.findall(r"[A-Za-z0-9\u00c0-\u024f]+(?:['’-][A-Za-z0-9]+)*", text))
    else:
        # 中文与混合：汉字数 + 拉丁词数（英文单词也算进去），按中文语速读
        rate = SPEECH_CJK_PER_MINUTE
        cjk = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))
        latin = len(re.findall(r"[A-Za-z0-9\u00c0-\u024f]+(?:['’-][A-Za-z0-9]+)*", text))
        units = cjk + latin
    if units <= 0:
        return 0.0
    return units / rate * 60.0


def describe_length(text: str) -> str:
    """一句话描述"这段文字有多长"——字数与时长的**单位随语言变**。

    返回例如 ``"1,560 字符 · 约 260 词 · 约 95 秒语音"``（英文）
    或 ``"320 字 · 约 80 秒语音"``（中文）。
    """
    if not text.strip():
        return L("0 字", "0 characters")
    language = language_of(text)
    parts: list = []
    if language == "en":
        words = len(re.findall(r"[A-Za-z0-9\u00c0-\u024f]+(?:['’-][A-Za-z0-9]+)*", text))
        parts.append(L(f"{words:,} 词", f"{words:,} words"))
    else:
        characters = len(re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", text))
        parts.append(L(f"{characters:,} 字", f"{characters:,} characters"))
    seconds = estimate_seconds(text)
    if seconds >= 1.0:
        parts.append(L(f"约 {seconds:.0f} 秒语音", f"~{seconds:.0f} sec speech"))
    return " · ".join(parts)


def request_parts(text: str) -> int:
    """上游会把文本按 4096 字节切成几段。返回段数，用于提示。"""
    if not text:
        return 0
    data = text.encode("utf-8")
    return max(1, (len(data) + MAX_REQUEST_BYTES - 1) // MAX_REQUEST_BYTES)


def display_path(path: str) -> str:
    r"""把路径统一成 Windows 的规范写法（反斜杠），用于**显示**。

    为什么需要它：同一个状态栏里出现了两种分隔符——用户实测报回来
    "路径格式都不统一"：

        D:/Temp/02.mp3      ← 正斜杠
        D:\Temp\02.srt      ← 反斜杠

    来源是两处不同的路径：
      * `filedialog` / `askdirectory` 在 Windows 上返回**正斜杠**的路径
        （tkinter 一律用正斜杠），存进配置后原样显示；
      * 而 `Path.with_suffix()` 之类规范化过的路径是**反斜杠**。

    对用户来说这是"同一个东西有两种写法"，看着就像没做完。所以在**显示**
    这一层统一：一律反斜杠。不改变实际使用的路径对象，只改字符串的写法。
    """
    if not path:
        return path
    # 反斜杠是 Windows 的规范写法；这里只做显示层的统一，
    # 不动真正的路径语义（`Path` 两种写法都能正确处理）。
    return str(path).replace("/", "\\")
