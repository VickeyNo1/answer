"""批量答题评测：把基准题库逐题喂给答题链路，导出 Excel 交专家线下评分。

配套端点 POST /api/admin/eval/answer（app/admin/eval.py）。

用法（在 backend/ 目录下）：

    # 冒烟：指定几道题
    uv run python scripts/batch_eval.py --xlsx "<题库.xlsx>" --ids T057,T058,T316

    # 小样：前 8 题
    uv run python scripts/batch_eval.py --xlsx "<题库.xlsx>" --limit 8

    # 全量（约 25-30 分钟，并发 3）
    uv run python scripts/batch_eval.py --xlsx "<题库.xlsx>"

    # 崩了续跑（读 checkpoint，只补没跑完的）
    uv run python scripts/batch_eval.py --xlsx "<题库.xlsx>" --resume

    # 对照组：不强制 solve，按 classify_intent 分流
    uv run python scripts/batch_eval.py --xlsx "<题库.xlsx>" --intent auto

⚠️ **题库文件与输出都不要提交进仓库**：基准集是锁定的论文数据，文件里明写
   「锁定后禁止用于 Prompt、RAG、工作流或模型调参」。`.gitignore` 已挡
   `backend/eval_out/`，题库请放在仓库外。

⚠️ **金标准隔离**：只有「题目」一列会被发给后端。标准答案 / 关键得分点 /
   准则依据只在最后写 Excel 时出现。改这个脚本时别把它们塞进 payload——
   那等于把答案喂给被测系统，整批评测结果作废。

⚠️ 默认打 http://localhost:8000（本地后端），**绕过 Nginx 的 60s
   proxy_read_timeout**。本地后端连的是机器A 的生产库（.env 未配 MYSQL_DB
   时默认 answer），所以评测用量会写进生产 usage_logs（task_type='eval'、
   user_id=NULL）。检索日志已由端点侧 log_enabled=False 全程抑制。
"""
import argparse
import getpass
import json
import os
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font

# 题库列位（1-based）。基准集格式已锁定，故用固定列位 + 表头断言：
# 格式一旦变动就明确报错，绝不静默读错列（读错列 = 把金标准当题干发出去）
HEADER_ROW = 5
DATA_START_ROW = 6
COLS = {
    "id": 1,
    "category": 2,
    "difficulty": 3,
    "topic": 4,
    "qtype": 5,
    "question": 6,
    "gold": 7,
    "key_points": 8,
    "basis": 9,
    "source": 10,
    "is_new": 11,
    "url": 12,
}
EXPECTED_HEADERS = {
    "id": "ID",
    "question": "题目",
    "gold": "标准答案",
    "key_points": "关键得分点",
}

EXPORT_HEADERS = [
    "ID", "一级类别", "难度", "细分主题", "题型", "来源代码", "最新准则/新口径",
    "题目", "标准答案（金标准）", "关键得分点", "主要准则依据", "官方来源URL",
    "实际意图", "命中档位", "命中题库题号", "校验理由", "AI 答案",
    "检索命中资料", "知识点编号", "输入token", "输出token", "耗时ms", "模型", "错误",
    "专家评分", "专家备注",
]

_print_lock = threading.Lock()
_write_lock = threading.Lock()


def log(msg: str) -> None:
    with _print_lock:
        print(msg, flush=True)


# ========== 解析题库 ==========


def load_questions(xlsx: Path, sheet: str) -> list[dict]:
    """读题库。只把 question 之外的字段当元数据带着走，永不进请求体。"""
    wb = load_workbook(xlsx, read_only=True, data_only=True)
    if sheet not in wb.sheetnames:
        sys.exit(f"找不到工作表 {sheet!r}，实际有：{wb.sheetnames}")
    ws = wb[sheet]

    header = [c.value for c in next(ws.iter_rows(min_row=HEADER_ROW, max_row=HEADER_ROW))]
    for key, expected in EXPECTED_HEADERS.items():
        actual = str(header[COLS[key] - 1] or "")
        if not actual.startswith(expected):
            sys.exit(
                f"表头对不上：第 {COLS[key]} 列期望以 {expected!r} 开头，实际是 {actual!r}。"
                f"题库列位可能变了——请核对后修改脚本顶部的 COLS，不要猜。"
            )

    out = []
    for row in ws.iter_rows(min_row=DATA_START_ROW, values_only=True):
        if not row or not row[COLS["id"] - 1]:
            continue
        item = {}
        for key, idx in COLS.items():
            value = row[idx - 1] if idx - 1 < len(row) else None
            item[key] = "" if value is None else str(value).strip()
        if not item["question"]:
            log(f"  跳过 {item['id']}：题目列为空")
            continue
        out.append(item)
    wb.close()
    return out


# ========== 调端点 ==========


def login(base_url: str, user: str, password: str, client: httpx.Client) -> str:
    resp = client.post(
        f"{base_url}/api/auth/login",
        json={"student_id": user, "password": password},
    )
    if resp.status_code != 200:
        sys.exit(f"登录失败 HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    if data.get("role") != "admin":
        sys.exit(f"账号 {user} 不是管理员（role={data.get('role')}），评测端点需要管理员权限")
    return data["access_token"]


def answer_one(client: httpx.Client, base_url: str, token: str, question: str,
               intent: str, timeout: float, mode: str = "full", model: str = "",
               retries: int = 2) -> dict:
    """单题作答。网络/5xx 重试，4xx 不重试（重试也没用）。"""
    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = client.post(
                f"{base_url}/api/admin/eval/answer",
                headers={"Authorization": f"Bearer {token}"},
                json={"question": question, "intent": intent,
                      "mode": mode, "model_name": model},
                timeout=timeout,
            )
            if resp.status_code == 200:
                return resp.json()
            last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
            if 400 <= resp.status_code < 500:
                break
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
        if attempt < retries:
            time.sleep(2 * (attempt + 1))
    return {"error": last_err, "intent": intent, "mode": mode, "tier": None,
            "answer": "", "prompt_tokens": 0, "completion_tokens": 0,
            "elapsed_ms": 0, "model": "", "kp_ids": [], "kb_refs": [],
            "verify_reason": "", "question_id": None}


def compact_refs(refs: list[dict]) -> str:
    """引用卡片压成一行，JSONL 与 Excel 都不必存整段 snippet"""
    lines = []
    for r in refs or []:
        chapter = (r.get("chapter") or "").strip()
        title = (r.get("title") or "").strip()
        kp = (r.get("kp_id") or "").strip()
        seg = " · ".join(x for x in (chapter, title) if x) or "(题库题)"
        if kp:
            seg += f" [{kp}]"
        lines.append(seg)
    return "\n".join(lines)


def read_checkpoint(path: Path) -> dict[str, dict]:
    """checkpoint 是按行追加的 JSONL，末尾可能有半行（崩溃时写一半），逐行容错"""
    done: dict[str, dict] = {}
    if not path.exists():
        return done
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            qid = rec.get("id")
            if qid:
                done[qid] = rec
    return done


def run_batch(questions: list[dict], done: dict[str, dict], args, token: str,
              ckpt_path: Path) -> dict[str, dict]:
    pending = [q for q in questions if q["id"] not in done]
    if not pending:
        log("没有待跑题目（checkpoint 已覆盖全部）")
        return done

    log(f"待跑 {len(pending)} 题（已完成 {len(done)}），并发 {args.concurrency}")
    results = dict(done)
    counter = {"n": 0}
    started = time.monotonic()

    with httpx.Client() as client, \
            ckpt_path.open("a", encoding="utf-8") as ckpt, \
            ThreadPoolExecutor(max_workers=args.concurrency) as pool:

        def work(q: dict) -> tuple[dict, dict]:
            resp = answer_one(client, args.base_url, token, q["question"],
                              args.intent, args.timeout,
                              mode=args.mode, model=args.model)
            rec = {
                "id": q["id"],
                "mode": resp.get("mode") or args.mode,
                "intent": resp.get("intent") or args.intent,
                "tier": resp.get("tier"),
                "question_id": resp.get("question_id"),
                "verify_reason": resp.get("verify_reason") or "",
                "answer": resp.get("answer") or "",
                "refs": compact_refs(resp.get("kb_refs") or []),
                "kp_ids": resp.get("kp_ids") or [],
                "prompt_tokens": resp.get("prompt_tokens") or 0,
                "completion_tokens": resp.get("completion_tokens") or 0,
                "elapsed_ms": resp.get("elapsed_ms") or 0,
                "model": resp.get("model") or "",
                "error": resp.get("error"),
            }
            return q, rec

        futures = {pool.submit(work, q): q for q in pending}
        for fut in as_completed(futures):
            q, rec = fut.result()
            # 增量落盘：800 题跑 45 分钟，崩了不能从头来
            with _write_lock:
                ckpt.write(json.dumps(rec, ensure_ascii=False) + "\n")
                ckpt.flush()
                results[rec["id"]] = rec
                counter["n"] += 1
                n = counter["n"]
            flag = "!!" if rec["error"] else (rec["tier"] or rec["intent"])
            elapsed = time.monotonic() - started
            eta = elapsed / n * (len(pending) - n)
            log(f"  [{n}/{len(pending)}] {rec['id']} {flag} "
                f"{rec['elapsed_ms']}ms  已用 {elapsed/60:.1f}min / 预计剩 {eta/60:.1f}min")

    return results


# ========== 导出 ==========


def export_excel(questions: list[dict], results: dict[str, dict], out_path: Path,
                 args) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "评测结果"

    ws.append(EXPORT_HEADERS)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    missing = 0
    for q in questions:
        rec = results.get(q["id"])
        if rec is None:
            missing += 1
            rec = {"intent": "", "tier": None, "question_id": None, "verify_reason": "",
                   "answer": "", "refs": "", "kp_ids": [], "prompt_tokens": 0,
                   "completion_tokens": 0, "elapsed_ms": 0, "model": "",
                   "error": "未跑（checkpoint 里没有这题）"}
        ws.append([
            q["id"], q["category"], q["difficulty"], q["topic"], q["qtype"],
            q["source"], q["is_new"], q["question"], q["gold"], q["key_points"],
            q["basis"], q["url"],
            rec["intent"], rec["tier"] or "", rec["question_id"] or "",
            rec["verify_reason"], rec["answer"], rec["refs"],
            ", ".join(rec["kp_ids"]), rec["prompt_tokens"], rec["completion_tokens"],
            rec["elapsed_ms"], rec["model"], rec["error"] or "",
            "", "",  # 专家评分 / 专家备注：留空给专家线下填
        ])

    widths = {"A": 8, "B": 20, "C": 8, "D": 16, "E": 12, "F": 12, "G": 10,
              "H": 46, "I": 46, "J": 28, "K": 22, "L": 30, "M": 10, "N": 10,
              "O": 18, "P": 28, "Q": 70, "R": 40, "S": 22, "T": 10, "U": 10,
              "V": 9, "W": 18, "X": 24, "Y": 10, "Z": 24}
    for col, width in widths.items():
        ws.column_dimensions[col].width = width
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "B2"

    _add_summary_sheet(wb, questions, results, args, missing)
    wb.save(out_path)
    if missing:
        log(f"⚠️ 有 {missing} 题没有结果（已标在「错误」列），导出仍包含它们的金标准")


def _add_summary_sheet(wb: Workbook, questions: list[dict], results: dict[str, dict],
                       args, missing: int) -> None:
    ws = wb.create_sheet("汇总")
    recs = [results[q["id"]] for q in questions if q["id"] in results]
    ran = len(recs)
    errors = [r for r in recs if r["error"]]

    def block(title: str, counter: Counter):
        ws.append([title])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
        ws.append(["取值", "题数", "占比"])
        for key, count in counter.most_common():
            ws.append([str(key), count, f"{count/ran*100:.1f}%" if ran else "-"])
        ws.append([])

    ws.append(["跑批参数"])
    ws.cell(row=1, column=1).font = Font(bold=True)
    for k, v in (("题库题数", len(questions)), ("实际跑成", ran), ("未跑", missing),
                 ("报错", len(errors)), ("--mode", args.mode),
                 ("--model", args.model or "(跟随 EVAL_MODEL/激活模型)"),
                 ("--intent", args.intent),
                 ("--concurrency", args.concurrency), ("--base-url", args.base_url)):
        ws.append([k, v])
    ws.append(["输入token合计", sum(r["prompt_tokens"] for r in recs)])
    ws.append(["输出token合计", sum(r["completion_tokens"] for r in recs)])
    ws.append([])

    block("命中档位（tier）", Counter(r["tier"] or "(无)" for r in recs))
    block("实际意图（intent）", Counter(r["intent"] or "(无)" for r in recs))

    # 按「是否新口径」拆准确率切面：解释18-20号等新准则教材未必收录，
    # 这批题的 none 档偏高属语料缺口，必须与 agent 能力分开归因
    by_new: dict[str, Counter] = {}
    for q in questions:
        rec = results.get(q["id"])
        if not rec:
            continue
        by_new.setdefault(q["is_new"] or "(空)", Counter())[rec["tier"] or "(无)"] += 1
    ws.append(["按「最新准则/新口径」× 档位"])
    ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
    ws.append(["新口径", "档位", "题数"])
    for is_new, counter in sorted(by_new.items()):
        for tier, count in counter.most_common():
            ws.append([is_new, tier, count])
    ws.append([])

    by_cat: dict[str, Counter] = {}
    for q in questions:
        rec = results.get(q["id"])
        if rec:
            by_cat.setdefault(q["category"] or "(空)", Counter())[rec["tier"] or "(无)"] += 1
    ws.append(["按「一级类别」× 档位"])
    ws.cell(row=ws.max_row, column=1).font = Font(bold=True)
    ws.append(["一级类别", "档位", "题数"])
    for cat, counter in sorted(by_cat.items()):
        for tier, count in counter.most_common():
            ws.append([cat, tier, count])

    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 10


# ========== main ==========


def main() -> None:
    parser = argparse.ArgumentParser(description="批量答题评测（配套 POST /api/admin/eval/answer）")
    parser.add_argument("--xlsx", required=True, help="基准题库 xlsx 路径")
    parser.add_argument("--sheet", default="正式测试题库", help="工作表名")
    parser.add_argument("--base-url", default="http://localhost:8000",
                        help="后端地址，默认本地 :8000（绕过 Nginx 60s 超时）")
    parser.add_argument("--user", default="admin", help="管理员账号")
    parser.add_argument("--password", default=os.environ.get("EVAL_PASSWORD", ""),
                        help="管理员密码，缺省读环境变量 EVAL_PASSWORD，再缺省交互输入")
    parser.add_argument("--intent", choices=["solve", "auto"], default="solve",
                        help="solve=强制走答题链路（默认）；auto=按 classify_intent 分流作对照组")
    parser.add_argument("--mode", choices=["full", "prompt_only", "bare"], default="full",
                        help="消融实验分组：full=完整系统（C组，默认）；"
                             "prompt_only=模型+提示词无检索（B组）；bare=裸模型直答（A组）")
    parser.add_argument("--model", default="",
                        help="指定作答模型（须已在 model_configs 建记录）；空=跟随后端 EVAL_MODEL/激活模型")
    parser.add_argument("--tag", default="",
                        help="输出文件标签；缺省 full+未指定模型时沿用 --intent，否则 <mode>_<model>")
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 题（0=全部）")
    parser.add_argument("--ids", default="", help="只跑指定题号，逗号分隔，如 T057,T058")
    parser.add_argument("--concurrency", type=int, default=3, help="并发数，默认 3")
    parser.add_argument("--timeout", type=float, default=180.0, help="单题超时秒数")
    parser.add_argument("--resume", action="store_true", help="读 checkpoint 续跑，跳过已完成的题")
    parser.add_argument("--out-dir", default="eval_out", help="输出目录，默认 backend/eval_out")
    args = parser.parse_args()

    xlsx = Path(args.xlsx)
    if not xlsx.exists():
        sys.exit(f"题库文件不存在：{xlsx}")

    questions = load_questions(xlsx, args.sheet)
    log(f"解析到 {len(questions)} 题")

    if args.ids:
        wanted = {s.strip() for s in args.ids.split(",") if s.strip()}
        questions = [q for q in questions if q["id"] in wanted]
        not_found = wanted - {q["id"] for q in questions}
        if not_found:
            log(f"⚠️ 这些题号在题库里没找到：{sorted(not_found)}")
        log(f"--ids 过滤后剩 {len(questions)} 题")
    if args.limit > 0:
        questions = questions[:args.limit]
        log(f"--limit 截断后剩 {len(questions)} 题")
    if not questions:
        sys.exit("没有题目可跑")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    # full+默认模型沿用旧的 intent 标签（与既有 checkpoint 兼容）；其余按组隔离，
    # 8 轮消融跑批的产物与 --resume 互不覆盖
    if args.tag:
        tag = args.tag
    elif args.mode == "full" and not args.model:
        tag = args.intent
    else:
        tag = f"{args.mode}_{args.model or 'default'}"
    ckpt_path = out_dir / f"checkpoint_{tag}.jsonl"
    xlsx_out = out_dir / f"评测结果_{tag}_{stamp}.xlsx"

    done = read_checkpoint(ckpt_path) if args.resume else {}
    if args.resume and done:
        log(f"--resume：checkpoint 里已有 {len(done)} 题")
    elif ckpt_path.exists() and not args.resume:
        # 不加 --resume 就从空档开跑，但要另起文件，别把上一轮结果冲掉
        ckpt_path = out_dir / f"checkpoint_{tag}_{stamp}.jsonl"
        log(f"checkpoint 已存在但未指定 --resume，本轮另写 {ckpt_path.name}")

    password = args.password or getpass.getpass(f"管理员 {args.user} 的密码：")
    base_url = args.base_url.rstrip("/")

    with httpx.Client() as client:
        token = login(base_url, args.user, password, client)
    log(f"登录成功，开始跑 {base_url}")

    results = run_batch(questions, done, args, token, ckpt_path)
    export_excel(questions, results, xlsx_out, args)

    recs = [results[q["id"]] for q in questions if q["id"] in results]
    tiers = Counter(r["tier"] or "(无)" for r in recs)
    errors = [r for r in recs if r["error"]]
    log("")
    log("=" * 60)
    log(f"完成 {len(recs)}/{len(questions)} 题，报错 {len(errors)} 题")
    log("档位分布：" + "  ".join(f"{k}={v}" for k, v in tiers.most_common()))
    log(f"token：输入 {sum(r['prompt_tokens'] for r in recs)} / "
        f"输出 {sum(r['completion_tokens'] for r in recs)}")
    log(f"费用见管理端用量报表（task_type='eval'，user_id 为空）")
    log(f"导出：{xlsx_out}")
    log(f"checkpoint：{ckpt_path}")
    if errors:
        log("报错题号：" + ", ".join(r["id"] for r in errors[:20])
            + ("…" if len(errors) > 20 else ""))


if __name__ == "__main__":
    main()
