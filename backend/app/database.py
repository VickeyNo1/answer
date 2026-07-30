"""MySQL 数据访问层：连接封装 + 建表（机器A MySQL 8.4）"""
from contextlib import contextmanager

import pymysql
from pymysql.cursors import DictCursor

from app.config import get_settings


class DB:
    """连接包装：提供与旧 sqlite3.Connection 相近的 execute/commit 接口，降低迁移面"""

    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql: str, params=None):
        cursor = self.conn.cursor()
        cursor.execute(sql, params or None)
        return cursor

    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    def close(self) -> None:
        self.conn.close()


def _connect(with_db: bool = True):
    """建立 MySQL 连接；with_db=False 时不选库（用于建库）"""
    settings = get_settings()
    return pymysql.connect(
        host=settings.MYSQL_HOST,
        port=settings.MYSQL_PORT,
        user=settings.MYSQL_USER,
        password=settings.MYSQL_PASSWORD,
        database=settings.MYSQL_DB if with_db else None,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
        connect_timeout=10,
    )


# 建表 SQL（MySQL 8.x / InnoDB / utf8mb4；存量库补注释见 scripts/add_table_comments.py）
TABLES_SQL = [
    """CREATE TABLE IF NOT EXISTS users (
        id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
        student_id VARCHAR(64) NOT NULL UNIQUE COMMENT '学号（登录账号，唯一）',
        password_hash VARCHAR(255) NOT NULL COMMENT 'bcrypt 密码哈希',
        name VARCHAR(64) NOT NULL COMMENT '姓名',
        role VARCHAR(16) NOT NULL DEFAULT 'student' COMMENT '角色：student=学生 / admin=管理员',
        daily_question_limit INT NULL COMMENT '单人每日提问上限；NULL=跟随全局默认（app_settings）',
        memory_enabled TINYINT NULL COMMENT '单人记忆开关：1=开 / 0=关；NULL=跟随全局默认',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户表（学生与管理员）'""",
    """CREATE TABLE IF NOT EXISTS conversations (
        id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
        user_id INT NOT NULL COMMENT '所属用户 ID（users.id）',
        title VARCHAR(255) NOT NULL DEFAULT '新对话' COMMENT '会话标题（取首条提问前 30 字）',
        subject VARCHAR(32) NULL COMMENT '科目枚举值（如 cpa_acc，由知识库侧维护）',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        INDEX idx_conversations_user (user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='对话会话表'""",
    """CREATE TABLE IF NOT EXISTS messages (
        id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
        conversation_id INT NOT NULL COMMENT '所属会话 ID（conversations.id）',
        role VARCHAR(16) NOT NULL COMMENT '消息角色：user=学生提问 / assistant=AI 回答',
        content MEDIUMTEXT NOT NULL COMMENT '消息正文（Markdown）',
        knowledge_point_ids TEXT NULL COMMENT '知识库命中知识点编号 JSON 数组（如 ["ACC-03-02-01"]）',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        INDEX idx_messages_conv (conversation_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='对话消息表'""",
    """CREATE TABLE IF NOT EXISTS model_configs (
        id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
        provider VARCHAR(16) NOT NULL DEFAULT 'ali' COMMENT '服务商：ali=通义千问 / deepseek=DeepSeek（均走百炼）',
        model_name VARCHAR(64) NOT NULL UNIQUE COMMENT '模型名（dashscope 调用标识，唯一）',
        display_name VARCHAR(64) NOT NULL COMMENT '展示名称',
        price_in DOUBLE NOT NULL DEFAULT 0 COMMENT '输入单价（元/千 token，管理员维护）',
        price_out DOUBLE NOT NULL DEFAULT 0 COMMENT '输出单价（元/千 token，管理员维护）',
        enabled TINYINT NOT NULL DEFAULT 1 COMMENT '是否启用：1=启用 / 0=停用',
        is_active TINYINT NOT NULL DEFAULT 0 COMMENT '是否当前使用模型：1=是（全表唯一）',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间'
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='大模型配置表'""",
    """CREATE TABLE IF NOT EXISTS usage_logs (
        id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
        model_name VARCHAR(64) NOT NULL COMMENT '使用的模型名',
        user_id INT NULL COMMENT '发起用户 ID（可空）',
        conversation_id INT NULL COMMENT '所属会话 ID（可空）',
        prompt_tokens INT NOT NULL DEFAULT 0 COMMENT '输入 token 数（Function Calling 两轮累加）',
        completion_tokens INT NOT NULL DEFAULT 0 COMMENT '输出 token 数（Function Calling 两轮累加）',
        total_tokens INT NOT NULL DEFAULT 0 COMMENT '总 token 数',
        cost DOUBLE NOT NULL DEFAULT 0 COMMENT '费用（元）= tokens/1000 × 单价',
        task_type VARCHAR(16) NOT NULL DEFAULT 'chat' COMMENT '任务类型：chat=对话/exam=判卷/profile=画像总结',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        INDEX idx_usage_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='大模型用量与费用日志表'""",
    """CREATE TABLE IF NOT EXISTS feedbacks (
        id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
        message_id INT NOT NULL UNIQUE COMMENT '被评价的 AI 消息 ID（messages.id，一条消息只能评一次）',
        user_id INT NOT NULL COMMENT '评价人 ID（users.id）',
        rating VARCHAR(8) NOT NULL COMMENT '评价：up=点赞 / down=点踩',
        reason VARCHAR(500) NULL COMMENT '点踩理由（rating=down 时必填，后端校验）',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        INDEX idx_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='答案反馈表（消息级点赞/点踩）'""",
    """CREATE TABLE IF NOT EXISTS kb_search_logs (
        id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
        user_id INT NOT NULL COMMENT '触发检索的用户 ID（users.id）',
        conversation_id INT NULL COMMENT '所属会话 ID（conversations.id，可空）',
        subject VARCHAR(32) NOT NULL COMMENT '科目枚举值（如 cpa_acc）',
        collection VARCHAR(16) NOT NULL COMMENT '检索集合：textbook=教材 / questions=题库',
        query VARCHAR(255) NOT NULL COMMENT '大模型生成的检索词',
        result_count INT NOT NULL DEFAULT 0 COMMENT '命中条数',
        kp_ids TEXT NULL COMMENT '命中知识点 ID，JSON 字符串格式（如 ["ACC-03-02-01"]，与 messages.knowledge_point_ids 一致）',
        status VARCHAR(16) NOT NULL COMMENT '检索状态：ok / empty / timeout / http_error / code_error（code≠0）/ degraded（重试后仍失败降级）',
        elapsed_ms INT NOT NULL DEFAULT 0 COMMENT '耗时毫秒',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
        INDEX idx_created (created_at)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知识库检索日志表（检索可观测）'""",
    """CREATE TABLE IF NOT EXISTS app_settings (
        id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
        setting_key VARCHAR(64) NOT NULL UNIQUE COMMENT '设置键',
        setting_value VARCHAR(255) NOT NULL COMMENT '设置值（统一存字符串，读取时转型）',
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='全局设置表（K-V 形式）'""",
    """CREATE TABLE IF NOT EXISTS exams (
        id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
        user_id INT NOT NULL COMMENT '考生 ID（users.id）',
        subject VARCHAR(32) NOT NULL COMMENT '科目枚举值（如 cpa_acc）',
        chapter_ids TEXT NULL COMMENT '章节范围 JSON 数组（如 ["ACC-03"]），NULL=全科目',
        status VARCHAR(16) NOT NULL DEFAULT 'ongoing' COMMENT '状态：ongoing=进行中 / grading=判卷中 / graded=已完成',
        question_count INT NOT NULL COMMENT '题目总数',
        total_score DECIMAL(5,1) NOT NULL COMMENT '试卷满分',
        obtained_score DECIMAL(5,1) NULL COMMENT '得分（判卷完成后写入）',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '开卷时间',
        submitted_at DATETIME NULL COMMENT '交卷时间',
        INDEX idx_user_status (user_id, status)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='试卷表'""",
    """CREATE TABLE IF NOT EXISTS exam_answers (
        id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键',
        exam_id INT NOT NULL COMMENT '所属试卷 ID（exams.id）',
        seq INT NOT NULL COMMENT '题号（1 起）',
        question_id VARCHAR(32) NOT NULL COMMENT '知识库题目 ID（如 Q-0012）',
        question_type VARCHAR(8) NOT NULL COMMENT '题型：单选/多选/计算/综合',
        question_snapshot TEXT NOT NULL COMMENT '题目快照 JSON（题干/选项/答案/解析/materials/sub_questions/knowledge_point_ids 全量，防知识库改题导致判卷错位）',
        full_score DECIMAL(5,1) NOT NULL COMMENT '本题满分',
        student_answer TEXT NULL COMMENT '学生作答（客观题存选项串如 "ABD"，主观题存文字）',
        score DECIMAL(5,1) NULL COMMENT '得分（NULL=未判/判卷失败）',
        llm_reason TEXT NULL COMMENT 'LLM 判分理由（仅主观题）',
        disputed TINYINT NOT NULL DEFAULT 0 COMMENT '学生异议标记：1=有异议',
        UNIQUE KEY uk_exam_seq (exam_id, seq)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='考试作答明细表（开卷时预置行）'""",
]

# 存量库幂等补列：表名 -> {列名: ALTER 语句}（新库已在 CREATE TABLE 中，仅缺列时执行）
EXTRA_COLUMNS = {
    "users": {
        "daily_question_limit": (
            "ALTER TABLE users ADD COLUMN daily_question_limit INT NULL "
            "COMMENT '单人每日提问上限；NULL=跟随全局默认（app_settings）'"
        ),
        "memory_enabled": (
            "ALTER TABLE users ADD COLUMN memory_enabled TINYINT NULL "
            "COMMENT '单人记忆开关：1=开 / 0=关；NULL=跟随全局默认'"
        ),
    },
    "usage_logs": {
        "task_type": (
            "ALTER TABLE usage_logs ADD COLUMN task_type VARCHAR(16) NOT NULL DEFAULT 'chat' "
            "COMMENT '任务类型：chat=对话/exam=判卷/profile=画像总结'"
        ),
    },
}


def init_db() -> None:
    """启动时执行：确保数据库存在并建表"""
    settings = get_settings()

    # 1. 确保数据库存在（需要账号有 CREATE 权限；已存在则跳过）
    conn = _connect(with_db=False)
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{settings.MYSQL_DB}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
            )
        conn.commit()
    finally:
        conn.close()

    # 2. 建表
    conn = _connect()
    try:
        with conn.cursor() as cursor:
            for sql in TABLES_SQL:
                cursor.execute(sql)

            # 3. 存量库幂等补列（新库建表已含，仅检测缺列时 ALTER）
            for table, columns in EXTRA_COLUMNS.items():
                cursor.execute(
                    "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
                    (settings.MYSQL_DB, table),
                )
                existing = {row["COLUMN_NAME"] for row in cursor.fetchall()}
                for column, alter_sql in columns.items():
                    if column not in existing:
                        cursor.execute(alter_sql)
        conn.commit()
    finally:
        conn.close()


def get_db():
    """FastAPI 依赖注入：返回数据库连接（生成器）"""
    db = DB(_connect())
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_ctx():
    """用于脚本/服务层的上下文管理器版本（如 seed.py）"""
    db = DB(_connect())
    try:
        yield db
    finally:
        db.close()
