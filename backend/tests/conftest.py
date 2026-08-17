"""pytest 公共夹具：每个测试独立的临时 SQLite 数据库 + 依赖注入的测试客户端。"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

# 保证 `import backend` 可用（无论从哪个目录启动 pytest）：
# backend 包位于仓库根目录（本文件在 backend/tests/ 下，向上两级）
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend import models  # noqa: E402,F401  确保 11 张表注册到 metadata
from backend.api.deps import get_db  # noqa: E402
from backend.main import create_app  # noqa: E402
from backend.models.base import Base  # noqa: E402


@pytest.fixture()
def db_session(tmp_path):
    """每个测试一个全新的临时 SQLite 数据库（打开外键约束）。"""
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    yield testing_session
    engine.dispose()


@pytest.fixture()
def client(db_session):
    """FastAPI 测试客户端：get_db 依赖指向临时数据库。"""
    app = create_app()

    def override_get_db():
        with db_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
