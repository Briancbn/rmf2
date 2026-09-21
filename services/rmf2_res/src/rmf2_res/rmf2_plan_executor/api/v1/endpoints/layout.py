import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from rmf2_res import crud
from rmf2_res.models import LifSummary
from rmf2_res.rmf2_plan_executor.api.deps.db import DbSession

router = APIRouter(prefix="/layout", tags=["layout"])


def _get_record(db: DbSession):
    record = crud.lif_record.get_current(db)
    if record is None:
        raise HTTPException(status_code=404, detail="No layout loaded")
    return record


@router.get("")
def get_layout_summary(db: DbSession) -> LifSummary:
    """Return layoutIds and metaInformation for the active LIF."""
    record = _get_record(db)
    layout_ids = json.loads(record.layout_ids_json) if record.layout_ids_json else []
    return LifSummary(
        layout_ids=layout_ids,
        project_identification=record.project_identification,
        creator=record.creator,
        export_timestamp=record.export_timestamp,
        lif_version=record.lif_version,
        loaded_at=record.loaded_at,
    )


@router.get("/download")
def download_layout(db: DbSession) -> Response:
    """Download the active LIF as a JSON file."""
    record = _get_record(db)
    filename = (
        f"{record.project_identification}.lif.json"
        if record.project_identification
        else "layout.lif.json"
    )
    return Response(
        content=record.lif_json,
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
