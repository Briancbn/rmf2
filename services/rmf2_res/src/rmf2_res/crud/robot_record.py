from __future__ import annotations

from sqlalchemy.orm import Session

from rmf2_res.crud.base import CRUDBase
from rmf2_res.db_models import RobotRecord

_RobotRecordCreate = dict[str, str | bool | None]


class CRUDRobotRecord(CRUDBase[RobotRecord, _RobotRecordCreate, _RobotRecordCreate]):
    def get(self, db: Session, robot_id: str) -> RobotRecord | None:  # type: ignore[override]
        return self.get_from_attr(db, "robot_id", robot_id)

    def create(self, db: Session, robot_id: str, **kwargs) -> RobotRecord:  # type: ignore[override]
        return super().create(db, obj_in={"robot_id": robot_id, **kwargs})

    def update(self, db: Session, robot_id: str, **kwargs) -> RobotRecord:  # type: ignore[override]
        return super().update(db, db_obj=self.get(db, robot_id), obj_in=kwargs)

    def reset_all_onboarded(self, db: Session) -> list[str]:
        records = db.query(RobotRecord).filter(RobotRecord.is_onboarded == True).all()
        robot_ids = [r.robot_id for r in records]
        for r in records:
            db.delete(r)
        db.commit()
        return robot_ids


robot_record = CRUDRobotRecord(RobotRecord)
