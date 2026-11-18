"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。
"""
from __future__ import annotations

from typing import Any

from app.seed import SEED_ROWS


class Store:
    def __init__(self) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        # 回滚预演批次：key 为回滚记录 id，value 为最近一次预演结果。
        self._rehearsals: dict[int, dict[str, Any]] = {}
        # 血缘影响清单：预演发布后写回，回滚列表与血缘页面共用这一份数据。
        self._lineage_impacts: list[dict[str, Any]] = []
        self._rehearsal_seq = 0

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def next_rehearsal_seq(self) -> int:
        self._rehearsal_seq += 1
        return self._rehearsal_seq

    def save_rehearsal(self, rollback_id: int, batch: dict[str, Any]) -> None:
        self._rehearsals[rollback_id] = batch

    def get_rehearsal(self, rollback_id: int) -> dict[str, Any] | None:
        return self._rehearsals.get(rollback_id)

    def list_rehearsals(self) -> list[dict[str, Any]]:
        return list(self._rehearsals.values())

    def replace_lineage_impacts(
        self, rollback_id: int, impacts: list[dict[str, Any]]
    ) -> None:
        """同一条回滚记录重复预演时，覆盖旧结论而不是追加，保证只发布一份完整边界结果。"""
        self._lineage_impacts = [
            row for row in self._lineage_impacts
            if int(row.get("回滚记录id", -1)) != rollback_id
        ]
        for row in impacts:
            published = dict(row)
            published["回滚记录id"] = rollback_id
            self._lineage_impacts.append(published)

    def lineage_impacts(self, rollback_id: int | None = None) -> list[dict[str, Any]]:
        if rollback_id is None:
            return list(self._lineage_impacts)
        return [
            row for row in self._lineage_impacts
            if int(row.get("回滚记录id", -1)) == rollback_id
        ]

    def reset(self) -> None:
        """恢复种子数据并清空预演产物，供测试用例之间隔离。"""
        self._tables = {
            name: [dict(row) for row in rows] for name, rows in SEED_ROWS.items()
        }
        self._rehearsals = {}
        self._lineage_impacts = []
        self._rehearsal_seq = 0

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


store = Store()
