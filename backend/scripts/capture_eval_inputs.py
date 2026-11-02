"""复现消融各组「每道题实际送入模型的检索正文 + 完整 messages 数组」。

零 LLM 调用、零费用：full 组只打机器A 的 :8100 检索服务；prompt_only / bare 两组
不检索，纯代码常量重建，连网络都不打。

背景：2026-09-16 消融跑批传 log_enabled=False，kb_search_logs 一行没写；checkpoint 的
refs 只存了 compact_refs 索引行，检索正文全文从未落盘。评审方要「当次究竟把哪些段落
全文交给了模型」。本脚本以 checkpoint 记录的 tier / refs 为当时档位与注入集合的真值，
按 run_solve 的检索调用序列原样重放，正文全文抓回后，用**生产代码自身的函数**
（build_messages / system_prompt_for / format_results / append_marker_notice /
_build_answer_messages）拼出与当时同构的完整 messages 数组。

逐题漂移校验：用重放结果重算 compact_refs，与 checkpoint 记录的 refs 逐字比对。
一致 = 该题正文可视为当时值；不一致 = 知识库索引自 2026-09-16 后有变动，drift=true，
交付时只能作「复现值」并标注复现日期，不得冒充当时快照。
prompt_only / bare 两组的 replayed_refs 恒为空串，故 drift=true 只可能是
「checkpoint 记到了非空 refs」= 检索桩没桩住，属实验定义被破坏，必须逐题查。

用法（backend/ 目录）：
    uv run python scripts/capture_eval_inputs.py --xlsx "<题库.xlsx>"
    uv run python scripts/capture_eval_inputs.py --xlsx "<题库.xlsx>" --ids T001,T057
    uv run python scripts/capture_eval_inputs.py --xlsx "<题库.xlsx>" \
        --ckpt eval_out/checkpoint_full_deepseek-v4-pro.jsonl
    uv run python scripts/capture_eval_inputs.py --xlsx "<题库.xlsx>" \
        --ckpt eval_out/checkpoint_prompt_only_glm-5.2.jsonl   # 离线，秒级
输出：backend/eval_out/captured_inputs_<ckpt文件名>.jsonl（目录已 gitignore）
"""
import argparse
import json
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))          # 复用 batch_eval 的题库列定位
sys.path.insert(0, str(_HERE.parent))   # backend 根，供 app.* 导入

import batch_eval
from app.chat import solver
from app.chat.qwen_service import build_messages
from app.kb import client as kb_client
from app.kb.prompt import append_marker_notice, format_results
from app.kb.subjects import DEFAULT_SUBJECT

_write_lock = threading.Lock()
INTENT_SOLVE = "solve"


def question_ids_from_refs(refs_str: str) -> list[str]:
    """compact_refs 索引行里题库行的题号，按注入顺序返回（similar 档反推注入子集用）"""
    ids = []
    for line in (refs_str or "").splitlines():
        m = re.search(r"题库 (\S+)", line)
        if m:
            ids.append(m.group(1))
    return ids


def replay(question: str, tier: str, question_id, recorded_refs: str) -> dict:
    """按 run_solve 的检索序列重放，返回检索全文与拼好的 messages"""
    q = question.strip()[: solver.QUERY_MAX_LEN]
    searches = []

    q_data = kb_client.search(query=q, subject=DEFAULT_SUBJECT, collection="questions",
                              top_k=3, log_enabled=False)
    q_results = (q_data or {}).get("results") or []
    searches.append({"collection": "questions", "query": q, "top_k": 3,
                     "results": q_results})

    parts: list[str] = []
    refs: list[dict] = []
    if tier == "exact":
        matched = next((r for r in q_results if r.get("question_id") == question_id), None)
        if matched is not None:
            parts.append(format_results({"collection": "questions", "results": [matched]},
                                        include_answer=True, heading=solver.EXACT_HEADING))
            refs.append(solver._question_ref(matched))
        t_data = s_data = None
    else:
        if tier == "similar":
            ids = question_ids_from_refs(recorded_refs)
            picked = [r for r in q_results if r.get("question_id") in ids]
            picked.sort(key=lambda r: ids.index(r.get("question_id")))
            if picked:
                parts.append(format_results({"collection": "questions", "results": picked},
                                            include_answer=True, heading=solver.SIMILAR_HEADING))
                refs.extend(solver._question_ref(r) for r in picked)
            text_query = solver._topic_query(picked, q)
            top_k, prefer = 5, None
        else:
            text_query, top_k, prefer = q, 8, "solve"

        t_data = kb_client.search(query=text_query, subject=DEFAULT_SUBJECT,
                                  collection="textbook", top_k=top_k, log_enabled=False)
        t_results = (t_data or {}).get("results") or []
        searches.append({"collection": "textbook", "query": text_query, "top_k": top_k,
                         "results": t_results})
        if t_results:
            parts.append(format_results(t_data, prefer=prefer))
            refs.extend(solver._textbook_refs(t_results))

        s_data = kb_client.search(query=q, subject=DEFAULT_SUBJECT, collection="standards",
                                  top_k=3, log_enabled=False)
        s_results = (s_data or {}).get("results") or []
        searches.append({"collection": "standards", "query": q, "top_k": 3,
                         "results": s_results})
        if s_results:
            parts.append(format_results(s_data))
            refs.extend(solver._standards_refs(s_results))

    context = append_marker_notice("\n\n".join(parts)) if parts else solver.NO_CONTEXT_TEXT
    block = {"exact": solver.EXACT_BLOCK, "similar": solver.SIMILAR_BLOCK}.get(
        tier, solver.NONE_BLOCK)
    messages = build_messages(question, [], None, solver.system_prompt_for(INTENT_SOLVE))
    final_messages = solver._build_answer_messages(messages, block, context)

    return {
        "searches": searches,
        "messages": final_messages,
        "replayed_refs": batch_eval.compact_refs(refs),
    }


def build_offline(question: str, mode: str) -> dict:
    """prompt_only / bare 两组的模型输入：没有检索腿，不打网络

    prompt_only（评审 M1）= run_solve(disable_kb=True)：三腿全跳过 → tier=none →
    资料段 NO_CONTEXT_TEXT、档位块 NONE_BLOCK，且 solver.py 明确 disable_kb 不算降级
    （DEGRADED_SUFFIX 是「检索服务挂了」）。因此输入与模型无关，三个模型逐字相同。
    bare（A 组）= admin/eval.py::_answer_bare：单条 user 消息，无 system prompt、
    无档位块、无资料段，且是非流式调用。
    """
    if mode == "bare":
        messages = [{"role": "user", "content": question}]
    else:
        base = build_messages(question, [], None, solver.system_prompt_for(INTENT_SOLVE))
        messages = solver._build_answer_messages(base, solver.NONE_BLOCK,
                                                 solver.NO_CONTEXT_TEXT)
    return {"searches": [], "messages": messages, "replayed_refs": ""}


def done_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    out = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                out.add(json.loads(line)["id"])
            except json.JSONDecodeError:
                continue
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=True)
    ap.add_argument("--sheet", default="正式测试题库")
    ap.add_argument("--ckpt", default="eval_out/checkpoint_full_qwen3.7-flash.jsonl")
    ap.add_argument("--ids", default="", help="只跑这些题号，逗号分隔")
    ap.add_argument("--concurrency", type=int, default=3)
    args = ap.parse_args()

    ckpt_path = Path(args.ckpt)
    out_path = Path("eval_out") / f"captured_inputs_{ckpt_path.stem}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    questions = {item["id"]: item for item in batch_eval.load_questions(Path(args.xlsx), args.sheet)}
    records = batch_eval.read_checkpoint(ckpt_path)
    only = {x.strip() for x in args.ids.split(",") if x.strip()}

    todo = []
    for qid, rec in records.items():
        if rec.get("mode") not in ("full", "prompt_only", "bare") or rec.get("error"):
            continue
        if only and qid not in only:
            continue
        if qid not in questions:
            print(f"  跳过 {qid}：题库里没有这题的题干")
            continue
        todo.append((qid, rec))
    todo = [(qid, rec) for qid, rec in todo if qid not in done_ids(out_path)]
    print(f"待复现 {len(todo)} 题（checkpoint 共 {len(records)} 条），并发 {args.concurrency}")

    drift = 0
    with open(out_path, "a", encoding="utf-8") as out:
        def work(pair):
            nonlocal drift
            qid, rec = pair
            mode = rec.get("mode")
            if mode == "full":
                got = replay(questions[qid]["question"], rec.get("tier") or "none",
                             rec.get("question_id"), rec.get("refs") or "")
            else:
                got = build_offline(questions[qid]["question"], mode)
            is_drift = got["replayed_refs"] != (rec.get("refs") or "")
            row = {
                "id": qid,
                "tier": rec.get("tier"),
                "model": rec.get("model"),
                "drift": is_drift,
                "recorded_refs": rec.get("refs") or "",
                "replayed_refs": got["replayed_refs"],
                "searches": got["searches"],
                "messages": got["messages"],
            }
            with _write_lock:
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
                out.flush()
                if is_drift:
                    drift += 1
            print(f"  {qid} tier={row['tier']} drift={is_drift}", flush=True)

        with ThreadPoolExecutor(max_workers=args.concurrency) as ex:
            list(ex.map(work, todo))

    print(f"完成：{out_path}；漂移 {drift} 题（drift=true 的正文只能作复现值交付）")


if __name__ == "__main__":
    main()
