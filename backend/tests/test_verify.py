"""题目同一性校验结果解析测试（v4.1，纯函数，不依赖数据库）

parse_verify_result 的容错是 solver 三档判定的保守性基石：任何解析失败都必须
返回 same=False，由调用方归入 similar 档。**绝不允许在没有正向确认时宣称命中原题**——
误报 exact 会让学生拿着别人的答案去考试。
"""
import pytest

from app.chat.solver import build_verify_prompt, parse_verify_result


class TestParseVerifyResult:
    def test_plain_json_same(self):
        out = parse_verify_result('{"same": true, "index": 2, "reason": "数据与问法一致"}')
        assert out == {"same": True, "index": 2, "reason": "数据与问法一致"}

    def test_plain_json_not_same(self):
        out = parse_verify_result('{"same": false, "index": null, "reason": "金额不同"}')
        assert out == {"same": False, "index": None, "reason": "金额不同"}

    def test_wrapped_in_code_fence(self):
        text = '```json\n{"same": true, "index": 1, "reason": "同一道题"}\n```'
        assert parse_verify_result(text)["same"] is True
        assert parse_verify_result(text)["index"] == 1

    def test_surrounding_chatter(self):
        text = '经过比对，我的判断是：{"same": true, "index": 3, "reason": "题干一致"} 以上。'
        out = parse_verify_result(text)
        assert out["same"] is True and out["index"] == 3

    def test_reason_contains_braces(self):
        """reason 里出现花括号时，find/rfind 仍能取到完整对象"""
        text = '{"same": false, "index": null, "reason": "候选{相似}但数据不同"}'
        out = parse_verify_result(text)
        assert out["same"] is False

    @pytest.mark.parametrize("text", [
        "",
        "我无法判断",
        "不是 JSON",
        "{不是合法 JSON}",
        '{"same": true, "index": ',        # 截断
        "[1, 2, 3]",                        # 非对象
        '{"same": "yes"}',                  # same 非布尔但真值 → 仍要求 index
    ])
    def test_malformed_never_raises(self, text):
        """任何畸形输入一律 same=False，不抛异常"""
        out = parse_verify_result(text)
        assert out["same"] is False
        assert out["index"] is None

    def test_same_without_index_degrades(self):
        """声称 same 却没给 index → 无法定位到具体题目 → 保守降级为 False"""
        out = parse_verify_result('{"same": true, "reason": "是同一道题"}')
        assert out["same"] is False
        assert out["reason"] == "是同一道题"

    @pytest.mark.parametrize("index", ["null", '"abc"', "{}", "[]", "1.5.2"])
    def test_same_with_unusable_index_degrades(self, index):
        out = parse_verify_result(f'{{"same": true, "index": {index}, "reason": "x"}}')
        assert out["same"] is False

    def test_same_with_string_digit_index_accepted(self):
        """模型常把数字写成字符串，"2" 应被接受（可定位即可）"""
        out = parse_verify_result('{"same": true, "index": "2", "reason": "x"}')
        assert out["same"] is True and out["index"] == 2

    def test_missing_reason_defaults_empty(self):
        out = parse_verify_result('{"same": false, "index": null}')
        assert out == {"same": False, "index": None, "reason": ""}

    def test_reason_coerced_to_string(self):
        out = parse_verify_result('{"same": false, "index": null, "reason": 123}')
        assert out["reason"] == "123"

    def test_false_with_stray_index_is_normalized_to_none(self):
        """same=false 时即便带了 index 也必须归零，防止调用方误用"""
        out = parse_verify_result('{"same": false, "index": 2, "reason": "x"}')
        assert out == {"same": False, "index": None, "reason": "x"}


class TestBuildVerifyPrompt:
    def test_includes_question_and_candidates(self):
        prompt = build_verify_prompt("甲公司购入存货", [
            {"question_id": "Q-1", "stem": "甲公司购入存货一批", "options": {"A": "甲", "B": "乙"}},
        ])
        assert "甲公司购入存货" in prompt
        assert "Q-1" in prompt
        assert "A.甲" in prompt and "B.乙" in prompt

    def test_never_includes_answer_or_explanation(self):
        """校验用不上答案，带上纯属浪费 token（且可能诱导模型按答案而非题干比对）"""
        prompt = build_verify_prompt("题干", [
            {"question_id": "Q-1", "stem": "题干", "answer": "B",
             "explanation": "因为存货属于流动资产"},
        ])
        assert "因为存货属于流动资产" not in prompt
        assert "答案" not in prompt

    def test_object_sub_questions_rendered_as_text(self):
        """子问是对象数组时不得把 dict repr 塞进 prompt"""
        prompt = build_verify_prompt("资料", [
            {"question_id": "Q-9", "materials": "甲公司资料",
             "sub_questions": [{"question": "编制购入分录", "answer": "借：存货"}, "计算成本"]},
        ])
        assert "编制购入分录" in prompt
        assert "计算成本" in prompt
        assert "借：存货" not in prompt        # 子问答案同样要剪裁
        assert "{" not in prompt               # dict repr 泄漏的特征

    def test_empty_candidates(self):
        assert "题干" in build_verify_prompt("题干", [])
