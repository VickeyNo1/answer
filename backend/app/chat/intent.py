"""提问意图三分类（v4.1）：solve 求解具体题目 / practice 要练习题 / consult 概念咨询

纯规则判定，**不加 LLM 调用**。敢用规则的理由是分类错误的两个方向都是优雅降级：

- solve 误判成 consult → 退回 Function Calling 自主检索路径（即改造前的现状行为），无损
- consult 误判成 solve → 走 solver 检索阶梯，题库未命中则据教材独立解答，答案依然正确，
  只是多附一句「未找到原题」标注与一次检索开销

所以分类器不必追求准确率。规则表可调，改完跑 tests/test_intent.py 即可。
"""
import re

INTENT_SOLVE = "solve"
INTENT_PRACTICE = "practice"
INTENT_CONSULT = "consult"

# 弱 solve 证据的长度门槛：短句子出现公司名/金额多半是举例，长文本才是题干
WEAK_SOLVE_MIN_LEN = 60

# 强 solve 标记（子串）：任一命中即判 solve，优先级高于 practice
_STRONG_SOLVE_KEYWORDS = (
    # 求助语气
    "怎么做", "怎么解", "怎么答", "如何解", "如何做", "求解", "算一下", "计算一下",
    "解答一下", "讲解一下", "答案是什么", "正确答案",
    # 指代某道具体的题
    "这道", "这个题", "那道", "该题", "本题", "此题", "上一题", "上面那道",
    # 题干结构特征
    "要求：", "要求:", "已知：", "已知:",
)

# 强 solve 标记（正则）
_STRONG_SOLVE_PATTERNS = (
    re.compile(r"(?:编制|写出|做出|做).{0,12}分录"),
    re.compile(r"第\s*\d+\s*题"),
    # 选择题括号空位（全角/半角）
    re.compile(r"[（(]\s*[)）]"),
    # 题型词开头带冒号，如「判断题：」「单选题：」
    re.compile(r"(?:单选题|多选题|判断题|计算题|综合题|简答题|分析题)\s*[:：]"),
    # 选择题题干句式，如「下列关于无形资产的表述中，正确的是」
    re.compile(r"(?:下列|以下|下述).{0,50}?(?:的是|的有|正确|错误|不正确|不属于)"),
)

# 选项行：A. / A、 / A) 起行
_OPTION_LINE = re.compile(r"^\s*[A-DＡ-Ｄ][.、．)）]", re.MULTILINE)
# 内联选项：学生粘贴题目时四个选项常挤在同一行，只靠行首匹配会漏判
_OPTION_INLINE = re.compile(r"[A-DＡ-Ｄ][.、．]")

# practice 标记（子串）
_PRACTICE_KEYWORDS = (
    "练习题", "真题", "模拟题", "刷题", "考考我", "测一测", "测验", "布置",
    "出几道", "出几题", "来几道", "来几题", "给我几道", "给我几题",
    "做几道", "做几题", "出题",
)

# 弱 solve 证据（子串）：需与长度门槛共同成立
_WEAK_SOLVE_KEYWORDS = (
    # 主体
    "甲公司", "乙公司", "丙公司", "某公司", "某企业", "A公司", "B公司",
    # 金额与年度
    "万元", "亿元", "元/股", "20×", "20X", "2×",
    # 题型词（用带「题」的完整词，避免「如何判断」这类概念提问被误伤）
    "单选题", "多选题", "判断题", "计算题", "综合题", "简答题", "分析题",
)


def _has_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(k in text for k in keywords)


def _has_strong_solve(text: str) -> bool:
    if _has_any(text, _STRONG_SOLVE_KEYWORDS):
        return True
    if any(p.search(text) for p in _STRONG_SOLVE_PATTERNS):
        return True
    if len(_OPTION_LINE.findall(text)) >= 2:
        return True
    return len(_OPTION_INLINE.findall(text)) >= 3


def _has_weak_solve(text: str) -> bool:
    return len(text) >= WEAK_SOLVE_MIN_LEN and _has_any(text, _WEAK_SOLVE_KEYWORDS)


def classify_intent(text: str | None, has_image: bool = False) -> str:
    """判定提问意图，返回 'solve' / 'practice' / 'consult'

    判定顺序即优先级，不可调换。强 solve 必须排在 practice 之前：
    「这道练习题怎么做」含 practice 标记，但学生要的是**这道题的答案**，
    不是再要几道题。
    """
    if has_image:
        # 拍照即求解（已定决策：图片直通 solve）
        return INTENT_SOLVE

    text = (text or "").strip()
    if not text:
        return INTENT_CONSULT

    if _has_strong_solve(text):
        return INTENT_SOLVE
    if _has_any(text, _PRACTICE_KEYWORDS):
        return INTENT_PRACTICE
    if _has_weak_solve(text):
        return INTENT_SOLVE
    return INTENT_CONSULT
