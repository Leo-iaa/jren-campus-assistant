"""计划编排服务门面（薄 re-export 层）。

实现拆分在同级模块，按职责一个文件：

- :mod:`plan_generator`  生成：课程/任务/复习/杂项 → 草案 → 规划器 → 落库
- :mod:`plan_lifecycle`  生命周期：确认（Notion 日历）/ 调整 / 完成（校准+画像）
- :mod:`plan_preview`    预览：计划 → 微信友好文本
- :mod:`task_intake`     任务录入：add_task + 增量插入 / ddl 腾挪
- :mod:`queries`         查询：课程 / 任务 / 复习列表
- :mod:`_common`         共享工具：时区 / 解析 / 时长 / 结果数据结构

本模块保持既有 ``from backend.mcp_server.service import X`` 导入路径兼容
（server.py / scheduler_jobs.py / running_service.py / 全部测试）。
新代码建议直接从具体模块导入。
"""
from backend.mcp_server._common import (  # noqa: F401
    AFTERNOON_END,
    DEFAULT_REVIEW_MINUTES,
    DEFAULT_TASK_MINUTES,
    ITEM_TYPE_LABELS,
    MAX_DURATION_MINUTES,
    MORNING_END,
    S_REVIEW_MINUTES,
    ConfirmResult,
    GeneratePlanResult,
    add_minutes,
    clamp_duration,
    duration_minutes,
    get_setting,
    hhmm_duration,
    item_to_dict,
    minutes_to_time,
    parse_date,
    parse_hhmm,
    parse_study_hours,
    shanghai_today,
    time_bucket_for,
    tomorrow,
)
from backend.mcp_server.plan_generator import generate_plan  # noqa: F401
from backend.mcp_server.plan_lifecycle import (  # noqa: F401
    adjust_plan_item,
    confirm_plan,
    mark_done,
)
from backend.mcp_server.plan_preview import preview_plan_text  # noqa: F401
from backend.mcp_server.queries import list_courses, list_reviews, list_tasks  # noqa: F401
from backend.mcp_server.task_intake import (  # noqa: F401
    TASK_TYPES,
    AddTaskResult,
    UpdateTaskResult,
    add_task,
    day_locked,
    find_free_slot,
    task_to_dict,
    update_task,
)

# 旧名兼容（测试 / running_service / scheduler_jobs 仍按旧名导入）
_get_setting = get_setting
_item_to_dict = item_to_dict
_find_free_slot = find_free_slot
_day_locked = day_locked
_task_to_dict = task_to_dict
_minutes_to_time = minutes_to_time
_clamp_duration = clamp_duration
_add_minutes = add_minutes
_hhmm_duration = hhmm_duration
_duration_minutes = duration_minutes
