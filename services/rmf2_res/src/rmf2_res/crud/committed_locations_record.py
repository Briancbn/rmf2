from __future__ import annotations

from sqlalchemy.orm import Session

from rmf2_res.crud.base import CRUDBase
from rmf2_res.db_models import CommittedLocationsRecord

_CommittedLocationsRecordCreate = dict[str, str]


class CRUDCommittedLocationsRecord(
    CRUDBase[CommittedLocationsRecord, _CommittedLocationsRecordCreate, _CommittedLocationsRecordCreate]
):
    def get(self, db: Session, request_id: str) -> CommittedLocationsRecord | None:  # type: ignore[override]
        return self.get_from_attr(db, "request_id", request_id)

    def create(self, db: Session, request_id: str, **kwargs) -> CommittedLocationsRecord:  # type: ignore[override]
        return super().create(db, obj_in={"request_id": request_id, **kwargs})

    def update(self, db: Session, request_id: str, **kwargs) -> CommittedLocationsRecord:  # type: ignore[override]
        return super().update(db, db_obj=self.get(db, request_id), obj_in=kwargs)


committed_locations_record = CRUDCommittedLocationsRecord(CommittedLocationsRecord)
