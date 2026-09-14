from __future__ import annotations

from sqlalchemy.orm import Session

from rmf2_res.crud.base import CRUDBase
from rmf2_res.db_models import TaskRecord

_TaskRecordCreate = dict[str, str | None]


class CRUDTaskRecord(CRUDBase[TaskRecord, _TaskRecordCreate, _TaskRecordCreate]):
    def get(self, db: Session, task_id: str) -> TaskRecord | None:  # type: ignore[override]
        return self.get_from_attr(db, "task_id", task_id)

    def create(self, db: Session, task_id: str, **kwargs) -> TaskRecord:  # type: ignore[override]
        return super().create(db, obj_in={"task_id": task_id, **kwargs})

    def update(self, db: Session, task_id: str, **kwargs) -> TaskRecord:  # type: ignore[override]
        return super().update(db, db_obj=self.get(db, task_id), obj_in=kwargs)


task_record = CRUDTaskRecord(TaskRecord)
