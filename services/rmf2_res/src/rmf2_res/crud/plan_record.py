from __future__ import annotations

from sqlalchemy.orm import Session

from rmf2_res.crud.base import CRUDBase
from rmf2_res.db_models import PlanRecord

_PlanRecordCreate = dict[str, str | int | None]


class CRUDPlanRecord(CRUDBase[PlanRecord, _PlanRecordCreate, _PlanRecordCreate]):
    def get(self, db: Session, plan_id: str) -> PlanRecord | None:  # type: ignore[override]
        return self.get_from_attr(db, "plan_id", plan_id)

    def create(self, db: Session, plan_id: str, **kwargs) -> PlanRecord:  # type: ignore[override]
        return super().create(db, obj_in={"plan_id": plan_id, **kwargs})

    def update(self, db: Session, plan_id: str, **kwargs) -> PlanRecord:  # type: ignore[override]
        return super().update(db, db_obj=self.get(db, plan_id), obj_in=kwargs)


plan_record = CRUDPlanRecord(PlanRecord)
