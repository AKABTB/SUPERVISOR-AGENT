"""Web REST 路由。交互层：只收发 + 转调核心层，判断全在核心层。

人格分裂落地：这里是"配置面板前的清醒管理者"侧——允许自由增删改目标、
改主攻、改频率。没有"拦改"（拦改只在 TG Bot 的执行方侧）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request

from ...core.project_manager import ProjectManager
from ...core.scheduler import parse_cadence
from ...storage import CountedAs, Database, GoalStatus
from .schemas import (
    GoalCreate,
    GoalOut,
    GoalPatch,
    LogItem,
    OverviewOut,
    PrimaryOut,
    StatsOut,
)

router = APIRouter(prefix="/api")


# ---- 依赖：从 app.state 取共享实例 ----

def _db(request: Request) -> Database:
    return request.app.state.db


def _pm(request: Request) -> ProjectManager:
    return request.app.state.pm


def _bot_configured(request: Request) -> bool:
    return bool(request.app.state.telegram_token)


# ---- 序列化助手 ----

def _goal_out(goal) -> GoalOut:
    _, desc = parse_cadence(goal.cadence)
    return GoalOut(
        id=goal.id,
        title=goal.title,
        is_primary=goal.is_primary,
        status=goal.status.value,
        cadence=goal.cadence,
        cadence_desc=desc,
        created_at=goal.created_at,
        deadline=goal.deadline,
    )


def _require_goal(db: Database, goal_id: int):
    goal = db.get_goal(goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail=f"没有 #{goal_id} 这个目标")
    return goal


# ---- 首屏总览 ----

@router.get("/overview", response_model=OverviewOut)
def overview(request: Request) -> OverviewOut:
    db = _db(request)
    pm = _pm(request)

    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    week_start = (now - timedelta(days=7)).isoformat()

    primary = pm.get_primary()
    primary_out = None
    if primary:
        nagged, delivered = db.goal_counters(primary.id)
        lv = db.last_verdict(primary.id)
        primary_out = PrimaryOut(
            goal=_goal_out(primary),
            nagged=nagged,
            delivered=delivered,
            last_verdict=lv.value if lv else None,
        )

    queue = [
        _goal_out(g)
        for g in db.list_goals(status=GoalStatus.ACTIVE)
        if not g.is_primary
    ]

    stats = StatsOut(
        active=db.count_active(),
        nagged_today=db.count_nags_since(today_start),
        delivered_this_week=db.count_deliveries_since(week_start),
    )

    return OverviewOut(
        bot_online=_bot_configured(request),
        primary=primary_out,
        queue=queue,
        stats=stats,
        logs=_recent_logs(db),
    )


def _recent_logs(db: Database, limit: int = 30) -> list[LogItem]:
    """把交货记录和催收记录合并成一条时间线。"""
    items: list[LogItem] = []

    for d in db.list_deliveries(limit=limit):
        # review 存的是 issues 的 JSON 数组；展示时化成一句
        text = _delivery_text(d)
        items.append(LogItem(
            kind="delivery", at=d.submitted_at, goal_id=d.goal_id,
            verdict=d.verdict.value, text=text,
        ))

    for n in db.list_nags(limit=limit):
        counted = "交了" if n.counted_as == CountedAs.SUBMITTED else "没交"
        reply = n.your_reply.strip()
        text = f"催收 · 记为「{counted}」" + (f"：{reply}" if reply else "")
        items.append(LogItem(
            kind="nag", at=n.nagged_at, goal_id=n.goal_id,
            verdict=n.counted_as.value, text=text,
        ))

    items.sort(key=lambda x: x.at, reverse=True)
    return items[:limit]


def _delivery_text(d) -> str:
    import json
    try:
        issues = json.loads(d.review) if d.review else []
    except (ValueError, TypeError):
        issues = []
    if d.verdict.value == "pass":
        return "交货 · 验收通过"
    if issues:
        return "交货 · 没过：" + "；".join(str(i) for i in issues)
    return "交货 · 没过"


# ---- 目标 CRUD ----

@router.get("/goals", response_model=list[GoalOut])
def list_goals(request: Request, status: str | None = None) -> list[GoalOut]:
    db = _db(request)
    st = GoalStatus(status) if status else None
    return [_goal_out(g) for g in db.list_goals(status=st)]


@router.post("/goals", response_model=GoalOut)
def create_goal(request: Request, body: GoalCreate) -> GoalOut:
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="目标不能为空")
    pm = _pm(request)
    goal, _became_primary = pm.add_goal(title, body.cadence)
    return _goal_out(goal)


@router.patch("/goals/{goal_id}", response_model=GoalOut)
def patch_goal(request: Request, goal_id: int, body: GoalPatch) -> GoalOut:
    db = _db(request)
    _require_goal(db, goal_id)
    if body.title is not None:
        t = body.title.strip()
        if not t:
            raise HTTPException(status_code=400, detail="标题不能为空")
        db.set_goal_title(goal_id, t)
    if body.cadence is not None:
        db.set_goal_cadence(goal_id, body.cadence.strip())
    return _goal_out(db.get_goal(goal_id))


@router.post("/goals/{goal_id}/primary", response_model=GoalOut)
def set_primary(request: Request, goal_id: int) -> GoalOut:
    pm = _pm(request)
    primary = pm.set_primary(goal_id)
    if primary is None:
        raise HTTPException(status_code=404, detail="没这个进行中的目标")
    return _goal_out(primary)


@router.post("/goals/{goal_id}/done", response_model=GoalOut)
def mark_done(request: Request, goal_id: int) -> GoalOut:
    pm = _pm(request)
    goal = pm.mark_done(goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail="没这个目标")
    return _goal_out(_db(request).get_goal(goal_id))


@router.post("/goals/{goal_id}/archive", response_model=GoalOut)
def archive_goal(request: Request, goal_id: int) -> GoalOut:
    db = _db(request)
    _require_goal(db, goal_id)
    db.set_goal_status(goal_id, GoalStatus.ARCHIVED)
    return _goal_out(db.get_goal(goal_id))
