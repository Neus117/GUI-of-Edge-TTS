"""语音目录：拉取、排序、过滤、解析用户输入。

界面里那个下拉框有 300 多项，**让它可用是这一层的事**：按语言分组、
把常用语言排前面、支持"en 女"这样的搜索。

上游把 ``Name`` 写成 ``Microsoft Server Speech Text to Speech Voice (en-US, AriaNeural)``，
``ShortName`` 写成 ``en-US-AriaNeural``。**两个字段排序结果不同**，
所以"下拉框显示 ``ShortName``、调用时按显示项的原始下标取"这条链必须
全程用同一个字段——原来的实现用 ``Name`` 建列表、用 ``ShortName`` 显示，
选出来的声音和显示的不是同一个。
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence

from .lang import L

# 常用语言排前面（美式英语 → 简体中文 → 其他中文 → 其他）
_PREFERRED_LOCALE_ORDER = ("en-US", "zh-CN", "zh-TW", "zh-HK", "en-GB")

# 网络不可用时的兜底：**只是让界面能起来**，不是"完整的可用语音列表"。
# 界面会明确提示"语音列表未加载成功"，不会假装这是全部。
FALLBACK_VOICES: tuple[tuple[str, str, str], ...] = (
    ("en-US-AriaNeural", "Female", "en-US"),
    ("en-US-AndrewMultilingualNeural", "Male", "en-US"),
    ("zh-CN-XiaoxiaoNeural", "Female", "zh-CN"),
    ("zh-CN-YunxiNeural", "Male", "zh-CN"),
)


@dataclass(frozen=True)
class Voice:
    """一条语音。"""

    short_name: str
    name: str
    locale: str
    gender: str
    friendly: str = ""

    @property
    def language(self) -> str:
        """语言前缀，例如 ``en-US-AdriNeural`` → ``en-US``。"""
        return self.locale or "-".join(self.short_name.split("-")[:2])

    @property
    def language_group(self) -> str:
        """语言族，例如 ``zh-CN`` → ``zh``。用于按语言分组显示。"""
        return self.language.split("-")[0].lower()

    @property
    def gender_label(self) -> str:
        return {
            "Female": L("女", "Female"),
            "Male": L("男", "Male"),
        }.get(self.gender, self.gender or "—")

    @property
    def display(self) -> str:
        """下拉框里显示的一行。

        语言已经写在 ``ShortName`` 的前两段里（``en-US``），不再重复；
        上游的 ``FriendlyName`` 经常就是 ``ShortName`` 本身，直接拼会得到
        ``en-US-AnaNeural  en-US-AnaNeural · 女``——既重复又更长，
        而"提示语太长会被截断"是排版问题（规范 20.8）。
        """
        extra = (self.friendly or "").strip()
        head = self.short_name
        if extra and extra.lower() not in self.short_name.lower():
            head = f"{head}  {extra}"
        return f"{head} · {self.gender_label}"

    @property
    def chat_name(self) -> str:
        """ShortName 末尾那段，例如 ``AriaNeural`` → ``Aria``。"""
        tail = self.short_name.split("-")[-1]
        return re.sub(r"(Multilingual)?Neural$", "", tail) or tail


def _sort_key(voice: Voice) -> tuple:
    language = voice.language
    rank = len(_PREFERRED_LOCALE_ORDER)
    # 注意：Locale 可能是 "zh-CN-liaoning" / "zh-CN-shaanxi" 这种方言。
    # 旧代码只做精确匹配，于是这两个中文声音被当成"其他语言"扔到列表尾部。
    for index, preferred in enumerate(_PREFERRED_LOCALE_ORDER):
        if language == preferred or language.startswith(preferred + "-"):
            rank = index
            break
    return (rank, language, voice.short_name)


def build_catalog(raw_voices: Iterable[dict]) -> List[Voice]:
    """把上游的原始列表整理成排好序的 :class:`Voice` 列表。"""
    voices: List[Voice] = []
    seen = set()
    for item in raw_voices:
        short = str(item.get("ShortName") or "").strip()
        if not short or short in seen:
            continue
        seen.add(short)
        voices.append(
            Voice(
                short_name=short,
                name=str(item.get("Name") or "").strip(),
                locale=str(item.get("Locale") or "").strip(),
                gender=str(item.get("Gender") or "").strip(),
                friendly=str((item.get("VoiceTag") or {}).get("FriendlyName") or "").strip()
                if isinstance(item.get("VoiceTag"), dict)
                else "",
            )
        )
    voices.sort(key=_sort_key)
    return voices


def fallback_catalog() -> List[Voice]:
    return [
        Voice(short_name=short, name=short, locale=locale, gender=gender, friendly=short)
        for short, gender, locale in FALLBACK_VOICES
    ]


class VoiceFetchCancelled(Exception):
    """界面关闭/换代理时主动取消语音列表请求；不是错误。"""


async def fetch_voices_async(proxy: Optional[str] = None, cancel=None) -> List[Voice]:
    """向上游要语音列表。异常原样抛出，由调用方决定怎么提示。

    ``cancel`` 是 ``threading.Event``：取消时**先在事件循环还活着的时候**
    取消 aiohttp 任务并等它清理 session，避免进程退出时出现
    "Unclosed client session / Event loop is closed" 的终端噪音。
    """
    import edge_tts  # pylint: disable=import-outside-toplevel

    if cancel is not None and cancel.is_set():
        raise VoiceFetchCancelled()
    task = asyncio.create_task(edge_tts.list_voices(proxy=proxy))
    try:
        while not task.done():
            if cancel is not None and cancel.is_set():
                task.cancel()
                raise VoiceFetchCancelled()
            await asyncio.sleep(0.05)
        return build_catalog(task.result())
    finally:
        if not task.done():
            task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass


def fetch_voices(
    proxy: Optional[str] = None,
    timeout: float = 20.0,
    cancel=None,
) -> List[Voice]:
    """同步版本，供界面在后台线程里调用。"""

    async def runner() -> List[Voice]:
        return await asyncio.wait_for(
            fetch_voices_async(proxy, cancel=cancel), timeout
        )

    return asyncio.run(runner())


class VoiceCatalog:
    """界面用的语音集合：支持搜索与"上次选的还在不在"两类查询。"""

    def __init__(self, voices: Sequence[Voice], loaded: bool = True) -> None:
        self.voices: List[Voice] = list(voices)
        self.loaded = loaded

    def __len__(self) -> int:
        return len(self.voices)

    def __iter__(self):
        return iter(self.voices)

    @classmethod
    def empty(cls) -> "VoiceCatalog":
        return cls([], loaded=False)

    @classmethod
    def fallback(cls) -> "VoiceCatalog":
        return cls(fallback_catalog(), loaded=False)

    def find(self, short_name: str) -> Optional[Voice]:
        for voice in self.voices:
            if voice.short_name == short_name:
                return voice
        return None

    def default_voice(self, preferred: str = "") -> Optional[Voice]:
        """选默认项：用户上次选的 → 美式英语第一个 → 列表第一个。"""
        if preferred:
            found = self.find(preferred)
            if found:
                return found
        for voice in self.voices:
            if voice.language == "en-US":
                return voice
        return self.voices[0] if self.voices else None

    def search(self, query: str, limit: int = 200) -> List[Voice]:
        """按 ``语言 / 性别 / 名字`` 过滤。

        支持的写法（大小写、空格随意）：

        * ``zh`` / ``en-US`` / ``日语``
        * ``女`` / ``男`` / ``female`` / ``male``
        * ``aria`` / ``晓晓``
        * 组合：``en 女``、``zh-CN 男``
        """
        tokens = [t for t in re.split(r"[\s,，]+", (query or "").strip()) if t]
        if not tokens:
            return self.voices[:limit]

        matched: List[Voice] = []
        for voice in self.voices:
            if all(_matches(voice, token) for token in tokens):
                matched.append(voice)
                if len(matched) >= limit:
                    break
        return matched


_GENDER_WORDS = {
    "女": "Female",
    "女性": "Female",
    "female": "Female",
    "f": "Female",
    "男": "Male",
    "男性": "Male",
    "male": "Male",
    "m": "Male",
}

_LANGUAGE_WORDS = {
    "英语": "en",
    "英文": "en",
    "english": "en",
    "中文": "zh",
    "汉语": "zh",
    "chinese": "zh",
    "日语": "ja",
    "日文": "ja",
    "japanese": "ja",
    "韩语": "ko",
    "韩文": "ko",
    "korean": "ko",
    "法语": "fr",
    "french": "fr",
    "德语": "de",
    "german": "de",
    "西班牙语": "es",
    "spanish": "es",
    "俄语": "ru",
    "russian": "ru",
}


def _matches(voice: Voice, token: str) -> bool:
    lowered = token.lower()
    gender = _GENDER_WORDS.get(lowered)
    if gender:
        return voice.gender == gender
    language = _LANGUAGE_WORDS.get(lowered)
    if language:
        return voice.language_group == language
    haystack = " ".join(
        (voice.short_name, voice.name, voice.locale, voice.friendly, voice.chat_name)
    ).lower()
    return lowered in haystack
