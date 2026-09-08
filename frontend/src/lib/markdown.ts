/** AI 回答里的 LaTeX 分隔符归一化
 *
 * 线上实测（38 条已存回答）模型混用两套分隔符：`$…$` / `$$…$$` 占多数，
 * `\(…\)` / `\[…\]` 出现在 4 条里。remark-math 只认前者，不归一化那 4 条的公式
 * 就仍是裸文本——正是本次要修的现象。
 */

/** 三反引号代码块（含流式过程中尚未闭合的），捕获组使其在 split 结果里占据奇数位 */
const CODE_FENCE = /(```[\s\S]*?(?:```|$))/g;

/** 成对匹配再替换：只动闭合的 `\(…\)`，落单的 `\(` 保持原样
 *
 * 不做逐字符替换的原因：若把落单的 `\(` 也变成 `$`，它会和正文里本来就有的
 * 美元符号配成一对，把中间整段中文吞进公式模式。
 * 替换值用函数而非字符串，避开 `$$`/`$&` 这类替换模式转义。
 */
const BLOCK_MATH = /\\\[([\s\S]*?)\\\]/g;
const INLINE_MATH = /\\\(([\s\S]*?)\\\)/g;

export function normalizeMathDelimiters(text: string): string {
  if (!text || text.indexOf("\\") === -1) return text;

  // 代码块里的 \( \) 是字面量，不能改；split 的奇数位是代码块，原样拼回
  return text
    .split(CODE_FENCE)
    .map((seg, i) =>
      i % 2 === 1
        ? seg
        : seg
            .replace(BLOCK_MATH, (_m, body: string) => `$$${body}$$`)
            .replace(INLINE_MATH, (_m, body: string) => `$${body}$`),
    )
    .join("");
}
