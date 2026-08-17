"""自适应校准模块（纯内存分桶统计，无 FastAPI / 数据库依赖）。

设计依据 docs/vision.md（习惯自适应）与 docs/architecture.md 2.6：
- 每次任务记录「预估耗时 vs 实际耗时」；按 课程 × 时段 × 难度 × 类型 分桶统计
- 修正系数 factor = ratio_sum / sample_count（平均实际/预估比值），默认 1.0
- 示例：连续 3 次发现高数作业实际是预估的 1.5 倍 → factor 1.5，自动上调该类任务预估

与数据库对接：``calibration_stats`` 表只存聚合统计（sample_count + ratio_sum + factor）。
本模块为纯内存实现，通过 :meth:`CalibrationServiceImpl.snapshot` 导出
（行结构与表字段一致），:meth:`CalibrationServiceImpl.load_snapshot` 从聚合数据恢复；
factor 始终由 sample_count / ratio_sum 重算，不信任外部传入的 factor 字段。
"""
from __future__ import annotations

from dataclasses import dataclass

#: 时段分桶（对齐 calibration_stats.time_bucket）
TIME_BUCKETS = ("morning", "afternoon", "evening")

#: 校准项类型（对齐 calibration_stats.item_type；杂项不参与校准）
ITEM_TYPES = ("task", "review")

DIFFICULTY_RANGE = range(1, 6)


@dataclass(frozen=True)
class BucketKey:
    """校准分桶键：课程 × 时段 × 难度 × 类型。"""

    course_id: int | None
    time_bucket: str
    difficulty: int | None
    item_type: str


@dataclass
class BucketStats:
    """单个分桶的聚合统计。"""

    sample_count: int = 0
    ratio_sum: float = 0.0

    @property
    def factor(self) -> float:
        """修正系数 = 实际/预估 比值的均值；无样本时默认 1.0。"""
        return self.ratio_sum / self.sample_count if self.sample_count else 1.0


class CalibrationServiceImpl:
    """实现 ``interfaces.CalibrationService`` 协议的自适应校准器。"""

    def __init__(self) -> None:
        self._buckets: dict[BucketKey, BucketStats] = {}

    def record(
        self,
        course_id: int | None,
        time_bucket: str,
        difficulty: int | None,
        item_type: str,
        estimated_minutes: int,
        actual_minutes: int,
    ) -> None:
        """记录一次完成情况，更新对应分桶的修正系数。

        参数：
            course_id: 课程 id（任务类可为 None）
            time_bucket: 'morning' | 'afternoon' | 'evening'
            difficulty: 知识点难度 1-5；任务类为 None
            item_type: 'task' | 'review'
            estimated_minutes: 预估耗时（分钟，必须 > 0）
            actual_minutes: 实际耗时（分钟，必须 >= 0）
        """
        _validate_bucket(time_bucket, difficulty, item_type)
        if estimated_minutes <= 0:
            raise ValueError(f"预估耗时必须 > 0，收到: {estimated_minutes!r}")
        if actual_minutes < 0:
            raise ValueError(f"实际耗时必须 >= 0，收到: {actual_minutes!r}")

        key = BucketKey(
            course_id=course_id,
            time_bucket=time_bucket,
            difficulty=difficulty,
            item_type=item_type,
        )
        stats = self._buckets.setdefault(key, BucketStats())
        stats.sample_count += 1
        stats.ratio_sum += actual_minutes / estimated_minutes

    def factor_for(
        self,
        course_id: int | None,
        time_bucket: str,
        difficulty: int | None,
        item_type: str,
    ) -> float:
        """查询某分桶的耗时修正系数（无样本返回默认 1.0）。"""
        _validate_bucket(time_bucket, difficulty, item_type)
        stats = self._buckets.get(
            BucketKey(
                course_id=course_id,
                time_bucket=time_bucket,
                difficulty=difficulty,
                item_type=item_type,
            )
        )
        return stats.factor if stats else 1.0

    def snapshot(self) -> list[dict]:
        """导出全部分桶聚合（行结构对齐 ``calibration_stats`` 表）。"""
        rows = []
        for key, stats in sorted(
            self._buckets.items(),
            key=lambda kv: (
                kv[0].course_id if kv[0].course_id is not None else -1,
                kv[0].time_bucket,
                kv[0].difficulty if kv[0].difficulty is not None else -1,
                kv[0].item_type,
            ),
        ):
            rows.append(
                {
                    "course_id": key.course_id,
                    "time_bucket": key.time_bucket,
                    "difficulty": key.difficulty,
                    "item_type": key.item_type,
                    "sample_count": stats.sample_count,
                    "ratio_sum": round(stats.ratio_sum, 6),
                    "factor": round(stats.factor, 6),
                }
            )
        return rows

    @classmethod
    def load_snapshot(cls, rows: list[dict]) -> "CalibrationServiceImpl":
        """从聚合行恢复分桶状态（factor 由 sample_count / ratio_sum 重算）。"""
        svc = cls()
        for row in rows:
            key = BucketKey(
                course_id=row["course_id"],
                time_bucket=row["time_bucket"],
                difficulty=row["difficulty"],
                item_type=row["item_type"],
            )
            svc._buckets[key] = BucketStats(
                sample_count=row["sample_count"],
                ratio_sum=row["ratio_sum"],
            )
        return svc


def _validate_bucket(time_bucket: str, difficulty: int | None, item_type: str) -> None:
    if time_bucket not in TIME_BUCKETS:
        raise ValueError(f"未知时段分桶: {time_bucket!r}（应为 morning/afternoon/evening）")
    if item_type not in ITEM_TYPES:
        raise ValueError(f"未知校准项类型: {item_type!r}（应为 task/review）")
    if difficulty is not None and difficulty not in DIFFICULTY_RANGE:
        raise ValueError(f"难度必须在 1-5 之间或为 None，收到: {difficulty!r}")
