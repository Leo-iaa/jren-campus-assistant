"""数据库引擎与会话管理。

- 单用户起步使用 SQLite，多用户时平滑迁移 PostgreSQL（见 docs/database.md）
- SQLite 默认不强制外键，必须为每个连接打开 ``PRAGMA foreign_keys=ON``，
  否则 ON DELETE CASCADE / SET NULL 不会生效
- ``init_db()`` 建表后执行轻量迁移：为已存在的旧表补充新列
  （``create_all`` 只建缺失的表，不会给已有表加列）
"""
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from backend.config import settings
from backend.models.base import Base

# SQLite 需要 check_same_thread=False（FastAPI 多线程处理请求）
_is_sqlite = settings.database_url.startswith("sqlite")
_connect_args = {"check_same_thread": False} if _is_sqlite else {}

engine = create_engine(settings.database_url, connect_args=_connect_args)


@event.listens_for(engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
    """每个新连接打开外键约束（仅 SQLite 需要）。"""
    if _is_sqlite:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


#: 轻量迁移清单：(表名, 新增列 DDL)。create_all 不会给已存在表加列，
#: 旧库升级时在此追加新列（幂等：缺列才执行 ALTER TABLE）。
_ALTER_COLUMNS: list[tuple[str, str]] = [
    ("tasks", "task_type TEXT"),  # 任务类型（作业/实验/考试/其他，add_task 写入）
    ("course_sessions", "starts_on TEXT"),  # 课程生效起始日期（含），闭区间；空=整学期
    ("course_sessions", "ends_on TEXT"),    # 课程生效结束日期（含），闭区间；空=整学期
]


def init_db() -> None:
    """建表（幂等）：基于 models 元数据创建所有缺失的表，并跑轻量迁移。"""
    Base.metadata.create_all(bind=engine)
    _rebuild_data_sources_check()
    _rebuild_courses_tier_check()
    _update_course_tiers()
    _migrate_legacy_columns()


#: 指定课程档位调整（Issue #74）：(课程名, 目标档位)。幂等：重复执行无副作用。
_COURSE_TIER_UPDATES: tuple[tuple[str, str], ...] = (
    ("数据库系统实验", "A"),
    ("航空航天材料工程", "S"),
)


def _update_course_tiers() -> None:
    """按 :data:`_COURSE_TIER_UPDATES` 调整指定课程档位（幂等数据迁移）。"""
    with engine.begin() as conn:
        for name, tier in _COURSE_TIER_UPDATES:
            conn.execute(
                text("UPDATE courses SET tier = :tier WHERE name = :name"),
                {"name": name, "tier": tier},
            )


def _rebuild_courses_tier_check() -> None:
    """courses 的 tier CHECK 约束变更时重建表并迁移数据（幂等，SQLite 专用）。

    Issue #74 废除 C 档：旧库约束含 'C' 时按「建新表 → 迁数据（C→B）→ 换名」
    重建；同时删除指定课程（已退课，用户点名删除，如钙钛矿）。
    幂等：新库约束已是 S/A/B，直接返回。
    """
    if not settings.database_url.startswith("sqlite"):
        return
    #: 随约束重建一并删除的课程名（用户已退课，如 Issue #74 的钙钛矿）
    dropped_courses = ("钙钛矿材料及其柔性光电子器件",)

    with engine.begin() as conn:
        ddl_row = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='courses'")
        ).scalar()
        if ddl_row is None:
            return  # 表还不存在（create_all 刚建，约束已是最新）
        if "'C'" not in (ddl_row or ""):
            return  # 约束已是最新（S/A/B）
        conn.execute(text("ALTER TABLE courses RENAME TO courses_old"))
        conn.execute(text(
            "CREATE TABLE courses ("
            "id INTEGER PRIMARY KEY, "
            "name VARCHAR NOT NULL, code VARCHAR, "
            "tier VARCHAR NOT NULL DEFAULT 'A' CHECK (tier IN ('S','A','B')), "
            "color VARCHAR, teacher VARCHAR, notes TEXT, "
            "created_at TEXT NOT NULL)"
        ))
        # C → B（Issue #74：废除 C 档，原 C 档课程并入 B 档）
        conn.execute(text(
            "INSERT INTO courses (id, name, code, tier, color, teacher, notes, created_at) "
            "SELECT id, name, code, "
            "CASE WHEN tier = 'C' THEN 'B' ELSE tier END, "
            "color, teacher, notes, created_at FROM courses_old"
        ))
        conn.execute(text("DROP TABLE courses_old"))
        for name in dropped_courses:
            conn.execute(
                text("DELETE FROM courses WHERE name = :name"), {"name": name}
            )


def _rebuild_data_sources_check() -> None:
    """data_sources 的 source_type CHECK 约束扩展时重建表（幂等，SQLite 专用）。

    SQLite 不支持 ALTER CHECK：新类型（如 coros，Issue #65）写入旧库会被
    旧约束拒绝。检测现库约束不含最新 SOURCE_TYPES 时，按
    「建新表 → 复制 → 换名」标准流程重建。
    """
    if not settings.database_url.startswith("sqlite"):
        return
    from backend.models.datasource import SOURCE_TYPES

    with engine.begin() as conn:
        ddl_row = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE type='table' AND name='data_sources'")
        ).scalar()
        if ddl_row is None:
            return  # 表还不存在（create_all 刚建，约束已是最新）
        if all(f"'{t}'" in (ddl_row or "") for t in SOURCE_TYPES):
            return  # 约束已是最新
        conn.execute(text("ALTER TABLE data_sources RENAME TO data_sources_old"))
        conn.execute(text(
            "CREATE TABLE data_sources ("
            "id INTEGER PRIMARY KEY, "
            f"source_type VARCHAR NOT NULL CHECK (source_type IN ({','.join(repr(t) for t in SOURCE_TYPES)})), "
            "name VARCHAR, config VARCHAR, "
            "enabled INTEGER NOT NULL DEFAULT 1, "
            "last_sync_at VARCHAR, created_at VARCHAR NOT NULL)"
        ))
        conn.execute(text(
            "INSERT INTO data_sources (id, source_type, name, config, enabled, last_sync_at, created_at) "
            "SELECT id, source_type, name, config, enabled, last_sync_at, created_at FROM data_sources_old"
        ))
        conn.execute(text("DROP TABLE data_sources_old"))


def _migrate_legacy_columns() -> None:
    """为已存在的旧表补充新列（幂等；仅 SQLite 需要，PG 走真实迁移工具）。"""
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as conn:
        for table, column_ddl in _ALTER_COLUMNS:
            column_name = column_ddl.split()[0]
            cols = [row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))]
            if column_name not in cols:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column_ddl}"))
