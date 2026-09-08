"""意图三分类测试（纯函数，不依赖数据库）

回归锚点见 test_consult 中的 "存货怎么计价？"——它是 tests/test_chat_sse.py:222
现有用例的输入，一旦被误判为 solve，该文件 test_chat_triggers_kb_search 会因
改走 solver 分支而失败。
"""
import pytest

from app.chat.intent import (
    INTENT_CONSULT,
    INTENT_PRACTICE,
    INTENT_SOLVE,
    WEAK_SOLVE_MIN_LEN,
    classify_intent,
)


@pytest.mark.parametrize("text", [
    # 求助语气
    "这道题怎么做",
    "这道练习题怎么做",          # 优先级：强 solve 压过 practice 标记
    "帮我看看这道综合题",
    "融资租赁这道题的答案是什么",
    "求解：某企业20×3年发生如下业务",
    "已知：某公司年初所有者权益为100万元。计算一下年末数。",
    # 题干结构特征
    "要求：编制购入设备的会计分录",
    "甲公司购入设备一台，要求编制会计分录。",
    "第3题不会做",
    # 选择题
    "下列各项中，属于企业流动资产的是（  ）。",
    "下列关于无形资产的表述中，正确的是",
    "下列关于存货的表述正确的是\nA.存货按成本计量\nB.存货按市价计量",
    "下列哪项属于流动资产？A.存货 B.厂房 C.设备 D.专利权",   # 选项内联排版
    # 题型词带冒号
    "判断题：资产的账面价值一定等于其计税基础。",
])
def test_solve_strong(text):
    assert classify_intent(text) == INTENT_SOLVE


def test_solve_weak_evidence_long_stem():
    """无强标记的长题干：靠公司名 + 长度门槛兜住"""
    text = ("甲公司20×3年1月1日以银行存款购入乙公司发行在外的普通股100万股，"
            "支付价款800万元，另支付相关交易费用5万元，占乙公司有表决权股份的30%。")
    assert len(text) >= WEAK_SOLVE_MIN_LEN
    assert classify_intent(text) == INTENT_SOLVE


def test_weak_evidence_needs_length():
    """同样的公司名出现在短句里是举例，不是题干"""
    assert classify_intent("甲公司是什么") == INTENT_CONSULT


@pytest.mark.parametrize("text", [
    "给我几道租赁的练习题",
    "考考我，来几道固定资产的真题",
    "出几道长期股权投资的题",
    "有没有存货的模拟题",
    "我想刷题",
    "老师布置了测验，帮我准备一下",
])
def test_practice(text):
    assert classify_intent(text) == INTENT_PRACTICE


@pytest.mark.parametrize("text", [
    "什么是融资租赁？",
    "存货怎么计价？",                     # ← test_chat_sse.py:222 回归锚点
    "融资租赁的账务处理是怎样的",
    "解释一下权责发生制",
    "长期股权投资权益法和成本法的区别",
    "固定资产折旧方法有哪些",
    "如何判断一项租赁是否属于融资租赁",
    "什么是借贷记账法？",
    "资产=负债+所有者权益 是什么意思",
    "能举个例子吗？",
    "你好",
    "1+1等于几？",
    "第二问",
    "并发提问",
    "test",
])
def test_consult(text):
    assert classify_intent(text) == INTENT_CONSULT


def test_empty_and_none_are_consult():
    assert classify_intent("") == INTENT_CONSULT
    assert classify_intent(None) == INTENT_CONSULT
    assert classify_intent("   ") == INTENT_CONSULT


@pytest.mark.parametrize("text", ["", "什么是会计", "给我几道练习题"])
def test_image_always_solve(text):
    """拍照直通 solve（已定决策）：即使文字部分看着像 consult 或 practice"""
    assert classify_intent(text, has_image=True) == INTENT_SOLVE
