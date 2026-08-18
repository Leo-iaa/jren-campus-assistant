"""数据源绑定 CRUD + 同步 / 启停 / Notion OAuth。

- CRUD：绑定、列表、详情、部分更新、解绑
- 启停：POST /{id}/enable、POST /{id}/disable（等价于 PATCH enabled，语义更直白）
- 同步：POST /{id}/sync → 调用对应 MCP adapter 落库并更新 last_sync_at
- OAuth：POST /notion/oauth/start（生成授权 URL）与 /notion/oauth/callback（兑换 token）
"""
import os

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from backend.api.deps import apply_updates, get_db, get_or_404
from backend.mcp_client.oauth import generate_code_verifier, generate_state
from backend.mcp_client.service import (
    SyncAuthError,
    SyncError,
    _load_config,
    _save_config,
    _token_dict,
    build_oauth_client,
    sync_data_source,
)
from backend.mcp_client.transport import JsonRpcError
from backend.models import DataSource
from backend.schemas.datasource import (
    DataSourceCreate,
    DataSourceRead,
    DataSourceType,
    DataSourceUpdate,
    OAuthCallbackRead,
    OAuthCallbackRequest,
    OAuthStartRead,
    OAuthStartRequest,
    SyncRequest,
    SyncResultRead,
)

router = APIRouter(prefix="/data-sources", tags=["数据源"])


@router.get("", response_model=list[DataSourceRead], summary="数据源列表（可按类型过滤）")
def list_data_sources(
    source_type: DataSourceType | None = None, db: Session = Depends(get_db)
):
    query = db.query(DataSource)
    if source_type is not None:
        query = query.filter(DataSource.source_type == source_type)
    return query.order_by(DataSource.id).all()


@router.post("", response_model=DataSourceRead, status_code=201, summary="绑定数据源")
def create_data_source(payload: DataSourceCreate, db: Session = Depends(get_db)):
    source = DataSource(**payload.model_dump())
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


@router.get("/{source_id}", response_model=DataSourceRead, summary="数据源详情")
def get_data_source(source_id: int, db: Session = Depends(get_db)):
    return get_or_404(db, DataSource, source_id)


@router.patch("/{source_id}", response_model=DataSourceRead, summary="更新数据源（部分字段）")
def update_data_source(
    source_id: int, payload: DataSourceUpdate, db: Session = Depends(get_db)
):
    source = get_or_404(db, DataSource, source_id)
    apply_updates(source, payload.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(source)
    return source


@router.delete("/{source_id}", status_code=204, summary="解绑数据源")
def delete_data_source(source_id: int, db: Session = Depends(get_db)):
    source = get_or_404(db, DataSource, source_id)
    db.delete(source)
    db.commit()
    return Response(status_code=204)


# ---------- 启停 ----------


def _set_enabled(source_id: int, enabled: int, db: Session) -> DataSource:
    source = get_or_404(db, DataSource, source_id)
    source.enabled = enabled
    db.commit()
    db.refresh(source)
    return source


@router.post("/{source_id}/enable", response_model=DataSourceRead, summary="启用数据源")
def enable_data_source(source_id: int, db: Session = Depends(get_db)):
    return _set_enabled(source_id, 1, db)


@router.post("/{source_id}/disable", response_model=DataSourceRead, summary="禁用数据源")
def disable_data_source(source_id: int, db: Session = Depends(get_db)):
    return _set_enabled(source_id, 0, db)


# ---------- 同步 ----------


@router.post("/{source_id}/sync", response_model=SyncResultRead, summary="触发数据源同步（更新 last_sync_at）")
def sync_source(source_id: int, payload: SyncRequest | None = None, db: Session = Depends(get_db)):
    source = get_or_404(db, DataSource, source_id)
    if not source.enabled:
        raise HTTPException(status_code=409, detail="数据源已禁用，请先启用（POST /api/data-sources/{id}/enable）")
    try:
        result = sync_data_source(
            db,
            source,
            ics_content=payload.ics_content if payload else None,
            mode=payload.mode if payload else "merge",
            query=payload.query if payload else None,
            database_id=payload.database_id if payload else None,
        )
    except SyncAuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except SyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except JsonRpcError as exc:
        raise HTTPException(status_code=502, detail=f"MCP 调用失败：{exc}") from exc
    db.commit()
    return result


# ---------- Notion OAuth ----------


@router.post("/notion/oauth/start", response_model=OAuthStartRead, summary="Notion OAuth 起点：生成授权 URL")
def notion_oauth_start(payload: OAuthStartRequest | None = None, db: Session = Depends(get_db)):
    config: dict = {}
    if payload is not None and payload.source_id is not None:
        source = get_or_404(db, DataSource, payload.source_id)
        if source.source_type != "notion":
            raise HTTPException(status_code=400, detail="该数据源不是 notion 类型")
        config = _load_config(source)
    else:
        source = DataSource(source_type="notion", name="Notion", config="{}", enabled=1)
        db.add(source)
        db.flush()

    client_id = (
        (payload.client_id if payload else None)
        or config.get("client_id")
        or os.environ.get("JREN_NOTION_CLIENT_ID")
    )
    redirect_uri = (
        (payload.redirect_uri if payload else None)
        or config.get("redirect_uri")
        or "http://localhost:5173/#/oauth/notion/callback"
    )
    if not client_id:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail="缺少 client_id：请配置 JREN_NOTION_CLIENT_ID 环境变量或在 config 中设置",
        )

    state = generate_state()
    code_verifier = generate_code_verifier()
    config.update(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "oauth_state": state,
            "oauth_code_verifier": code_verifier,
        }
    )
    _save_config(source, config)
    db.commit()
    db.refresh(source)

    try:
        oauth = build_oauth_client(config)
        authorization_url = oauth.authorization_url(state, code_verifier)
    except SyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return OAuthStartRead(source_id=source.id, authorization_url=authorization_url)


@router.post("/notion/oauth/callback", response_model=OAuthCallbackRead, summary="Notion OAuth 回调：兑换并保存 token")
def notion_oauth_callback(payload: OAuthCallbackRequest, db: Session = Depends(get_db)):
    source = get_or_404(db, DataSource, payload.source_id)
    config = _load_config(source)
    if config.get("oauth_state") != payload.state:
        raise HTTPException(status_code=400, detail="state 校验失败：请重新发起授权")
    try:
        oauth = build_oauth_client(config)
        token = oauth.exchange_code(payload.code, config["oauth_code_verifier"])
    except SyncError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # httpx 网络错误等 → 502
        raise HTTPException(status_code=502, detail=f"token 兑换失败：{exc}") from exc

    config["tokens"] = _token_dict(token)
    config.pop("oauth_state", None)
    config.pop("oauth_code_verifier", None)
    _save_config(source, config)
    db.commit()
    return OAuthCallbackRead(source_id=source.id)
