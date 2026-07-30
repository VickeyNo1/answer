"""存量库补充表注释与字段注释（幂等，可重复执行）。

用法（backend 目录下）：uv run python scripts/add_table_comments.py
注意：
- 与 app/database.py::TABLES_SQL 中的注释保持一致，两处同改。
- MODIFY COLUMN 需复述完整列定义；故意省略 UNIQUE/PRIMARY KEY
  （索引已存在，复述会重复建索引）。
"""
import sys
from pathlib import Path

# 脚本位于 backend/scripts/，需把 backend 根目录加入模块搜索路径才能 import app
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import get_db_ctx

ALTER_SQL = [
    # ===== users =====
    "ALTER TABLE users COMMENT='用户表（学生与管理员）'",
    "ALTER TABLE users MODIFY id INT AUTO_INCREMENT COMMENT '主键'",
    "ALTER TABLE users MODIFY student_id VARCHAR(64) NOT NULL COMMENT '学号（登录账号，唯一）'",
    "ALTER TABLE users MODIFY password_hash VARCHAR(255) NOT NULL COMMENT 'bcrypt 密码哈希'",
    "ALTER TABLE users MODIFY name VARCHAR(64) NOT NULL COMMENT '姓名'",
    "ALTER TABLE users MODIFY role VARCHAR(16) NOT NULL DEFAULT 'student' COMMENT '角色：student=学生 / admin=管理员'",
    "ALTER TABLE users MODIFY created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'",
    # ===== conversations =====
    "ALTER TABLE conversations COMMENT='对话会话表'",
    "ALTER TABLE conversations MODIFY id INT AUTO_INCREMENT COMMENT '主键'",
    "ALTER TABLE conversations MODIFY user_id INT NOT NULL COMMENT '所属用户 ID（users.id）'",
    "ALTER TABLE conversations MODIFY title VARCHAR(255) NOT NULL DEFAULT '新对话' COMMENT '会话标题（取首条提问前 30 字）'",
    "ALTER TABLE conversations MODIFY subject VARCHAR(32) NULL COMMENT '科目枚举值（如 cpa_acc，由知识库侧维护）'",
    "ALTER TABLE conversations MODIFY created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'",
    # ===== messages =====
    "ALTER TABLE messages COMMENT='对话消息表'",
    "ALTER TABLE messages MODIFY id INT AUTO_INCREMENT COMMENT '主键'",
    "ALTER TABLE messages MODIFY conversation_id INT NOT NULL COMMENT '所属会话 ID（conversations.id）'",
    "ALTER TABLE messages MODIFY role VARCHAR(16) NOT NULL COMMENT '消息角色：user=学生提问 / assistant=AI 回答'",
    "ALTER TABLE messages MODIFY content MEDIUMTEXT NOT NULL COMMENT '消息正文（Markdown）'",
    'ALTER TABLE messages MODIFY knowledge_point_ids TEXT NULL COMMENT \'知识库命中知识点编号 JSON 数组（如 ["ACC-03-02-01"]）\'',
    "ALTER TABLE messages MODIFY created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'",
    # ===== model_configs =====
    "ALTER TABLE model_configs COMMENT='大模型配置表'",
    "ALTER TABLE model_configs MODIFY id INT AUTO_INCREMENT COMMENT '主键'",
    "ALTER TABLE model_configs MODIFY provider VARCHAR(16) NOT NULL DEFAULT 'ali' COMMENT '服务商：ali=通义千问 / deepseek=DeepSeek（均走百炼）'",
    "ALTER TABLE model_configs MODIFY model_name VARCHAR(64) NOT NULL COMMENT '模型名（dashscope 调用标识，唯一）'",
    "ALTER TABLE model_configs MODIFY display_name VARCHAR(64) NOT NULL COMMENT '展示名称'",
    "ALTER TABLE model_configs MODIFY price_in DOUBLE NOT NULL DEFAULT 0 COMMENT '输入单价（元/千 token，管理员维护）'",
    "ALTER TABLE model_configs MODIFY price_out DOUBLE NOT NULL DEFAULT 0 COMMENT '输出单价（元/千 token，管理员维护）'",
    "ALTER TABLE model_configs MODIFY enabled TINYINT NOT NULL DEFAULT 1 COMMENT '是否启用：1=启用 / 0=停用'",
    "ALTER TABLE model_configs MODIFY is_active TINYINT NOT NULL DEFAULT 0 COMMENT '是否当前使用模型：1=是（全表唯一）'",
    "ALTER TABLE model_configs MODIFY created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'",
    # ===== usage_logs =====
    "ALTER TABLE usage_logs COMMENT='大模型用量与费用日志表'",
    "ALTER TABLE usage_logs MODIFY id INT AUTO_INCREMENT COMMENT '主键'",
    "ALTER TABLE usage_logs MODIFY model_name VARCHAR(64) NOT NULL COMMENT '使用的模型名'",
    "ALTER TABLE usage_logs MODIFY user_id INT NULL COMMENT '发起用户 ID（可空）'",
    "ALTER TABLE usage_logs MODIFY conversation_id INT NULL COMMENT '所属会话 ID（可空）'",
    "ALTER TABLE usage_logs MODIFY prompt_tokens INT NOT NULL DEFAULT 0 COMMENT '输入 token 数（Function Calling 两轮累加）'",
    "ALTER TABLE usage_logs MODIFY completion_tokens INT NOT NULL DEFAULT 0 COMMENT '输出 token 数（Function Calling 两轮累加）'",
    "ALTER TABLE usage_logs MODIFY total_tokens INT NOT NULL DEFAULT 0 COMMENT '总 token 数'",
    "ALTER TABLE usage_logs MODIFY cost DOUBLE NOT NULL DEFAULT 0 COMMENT '费用（元）= tokens/1000 × 单价'",
    "ALTER TABLE usage_logs MODIFY task_type VARCHAR(16) NOT NULL DEFAULT 'chat' COMMENT '任务类型：chat=对话/exam=判卷/profile=画像总结'",
    "ALTER TABLE usage_logs MODIFY created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'",
    # ===== exams（v4.0-M2）=====
    "ALTER TABLE exams COMMENT='试卷表'",
    "ALTER TABLE exams MODIFY id INT AUTO_INCREMENT COMMENT '主键'",
    "ALTER TABLE exams MODIFY user_id INT NOT NULL COMMENT '考生 ID（users.id）'",
    "ALTER TABLE exams MODIFY subject VARCHAR(32) NOT NULL COMMENT '科目枚举值（如 cpa_acc）'",
    'ALTER TABLE exams MODIFY chapter_ids TEXT NULL COMMENT \'章节范围 JSON 数组（如 ["ACC-03"]），NULL=全科目\'',
    "ALTER TABLE exams MODIFY status VARCHAR(16) NOT NULL DEFAULT 'ongoing' COMMENT '状态：ongoing=进行中 / grading=判卷中 / graded=已完成'",
    "ALTER TABLE exams MODIFY question_count INT NOT NULL COMMENT '题目总数'",
    "ALTER TABLE exams MODIFY total_score DECIMAL(5,1) NOT NULL COMMENT '试卷满分'",
    "ALTER TABLE exams MODIFY obtained_score DECIMAL(5,1) NULL COMMENT '得分（判卷完成后写入）'",
    "ALTER TABLE exams MODIFY created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '开卷时间'",
    "ALTER TABLE exams MODIFY submitted_at DATETIME NULL COMMENT '交卷时间'",
    # ===== exam_answers（v4.0-M2）=====
    "ALTER TABLE exam_answers COMMENT='考试作答明细表（开卷时预置行）'",
    "ALTER TABLE exam_answers MODIFY id INT AUTO_INCREMENT COMMENT '主键'",
    "ALTER TABLE exam_answers MODIFY exam_id INT NOT NULL COMMENT '所属试卷 ID（exams.id）'",
    "ALTER TABLE exam_answers MODIFY seq INT NOT NULL COMMENT '题号（1 起）'",
    "ALTER TABLE exam_answers MODIFY question_id VARCHAR(32) NOT NULL COMMENT '知识库题目 ID（如 Q-0012）'",
    "ALTER TABLE exam_answers MODIFY question_type VARCHAR(8) NOT NULL COMMENT '题型：单选/多选/计算/综合'",
    "ALTER TABLE exam_answers MODIFY question_snapshot TEXT NOT NULL COMMENT '题目快照 JSON（题干/选项/答案/解析/materials/sub_questions/knowledge_point_ids 全量，防知识库改题导致判卷错位）'",
    "ALTER TABLE exam_answers MODIFY full_score DECIMAL(5,1) NOT NULL COMMENT '本题满分'",
    'ALTER TABLE exam_answers MODIFY student_answer TEXT NULL COMMENT \'学生作答（客观题存选项串如 "ABD"，主观题存文字）\'',
    "ALTER TABLE exam_answers MODIFY score DECIMAL(5,1) NULL COMMENT '得分（NULL=未判/判卷失败）'",
    "ALTER TABLE exam_answers MODIFY llm_reason TEXT NULL COMMENT 'LLM 判分理由（仅主观题）'",
    "ALTER TABLE exam_answers MODIFY disputed TINYINT NOT NULL DEFAULT 0 COMMENT '学生异议标记：1=有异议'",
]


def main() -> None:
    with get_db_ctx() as db:
        for sql in ALTER_SQL:
            db.execute(sql)
        db.commit()
    print(f"done: {len(ALTER_SQL)} 条 ALTER 已执行")


if __name__ == "__main__":
    main()
