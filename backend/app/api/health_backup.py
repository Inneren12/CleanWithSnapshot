from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter()

_BACKUP_MARKER = Path("/opt/backups/postgres/LAST_SUCCESS.txt")
_BACKUP_MAX_AGE_SECONDS = 26 * 3600  # 26 hours


@router.get("/healthz/backup")
def healthz_backup():
    if not _BACKUP_MARKER.exists():
        raise HTTPException(status_code=503, detail="backup marker missing")

    raw = _BACKUP_MARKER.read_text(encoding="utf-8").strip()
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        raise HTTPException(status_code=503, detail="backup marker invalid")

    age = (datetime.now(timezone.utc) - dt).total_seconds()
    if age > _BACKUP_MAX_AGE_SECONDS:
        raise HTTPException(status_code=503, detail=f"backup too old: {int(age)}s")

    return {"backup_ok": True, "last_backup_utc": raw, "age_seconds": int(age)}
