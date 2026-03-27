from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import json
import shutil
import tarfile
from typing import Any

from apscheduler.triggers.cron import CronTrigger
from bson import ObjectId
from bson.json_util import dumps as bson_dumps, loads as bson_loads

from app.db.mongo import db
from app.helpers.recurring_schedule import legacy_cron_to_time, parse_clock_time, parse_timezone_name
from app.services.admin_settings import get_admin_settings

BACKUP_COLLECTION = "backup_runs"
LOGO_UPLOAD_DIR = Path("app/frontend/static/uploads/logos")
EXCLUDED_COLLECTIONS = {BACKUP_COLLECTION}
BACKUP_INDEX_FILE = "backup_index.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_slug(value: str, fallback: str = "filesystem") -> str:
    raw = str(value or fallback).strip().lower()
    clean = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in raw)
    return clean.strip("-") or fallback


def _int_or_default(value: Any, default: int) -> int:
    try:
        parsed = int(str(value).strip())
        return parsed if parsed > 0 else default
    except Exception:
        return default


def _to_iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _backup_schedule_time(backup_cfg: dict) -> str:
    return str(backup_cfg.get("schedule_time") or legacy_cron_to_time(backup_cfg.get("schedule_cron"))).strip()


def _next_run_info(backup_cfg: dict, timezone_name: str) -> tuple[str | None, str | None]:
    enabled = bool(backup_cfg.get("enabled"))
    schedule_time = _backup_schedule_time(backup_cfg)
    if not enabled:
        return None, None
    if not schedule_time:
        return None, "Backup schedule time is enabled but time is empty."
    try:
        hour, minute = parse_clock_time(schedule_time)
        timezone_obj = parse_timezone_name(timezone_name)
        trigger = CronTrigger(hour=hour, minute=minute, timezone=timezone_obj)
        next_run = trigger.get_next_fire_time(None, _now())
        return _to_iso(next_run), None
    except ValueError as exc:
        return None, str(exc)


def validate_backup_config(backup_cfg: dict, timezone_name: str) -> None:
    provider = str(backup_cfg.get("provider") or "filesystem").strip().lower() or "filesystem"
    destination = str(backup_cfg.get("destination") or "").strip()
    enabled = bool(backup_cfg.get("enabled"))
    schedule_time = _backup_schedule_time(backup_cfg)
    retention_days = _int_or_default(backup_cfg.get("retention_days"), 7)

    if provider != "filesystem":
        raise ValueError("Only filesystem backup provider is supported right now.")
    if not destination:
        raise ValueError("Backup destination is required.")
    if retention_days <= 0:
        raise ValueError("Retention days must be a positive number.")
    parse_timezone_name(timezone_name)
    if enabled:
        if not schedule_time:
            raise ValueError("Backup time is required when backups are enabled.")
        parse_clock_time(schedule_time)


def describe_backup_config(backup_cfg: dict, timezone_name: str) -> dict:
    schedule_time = _backup_schedule_time(backup_cfg)
    normalized = {
        "enabled": bool(backup_cfg.get("enabled")),
        "provider": str(backup_cfg.get("provider") or "filesystem").strip() or "filesystem",
        "destination": str(backup_cfg.get("destination") or "").strip(),
        "schedule_time": schedule_time,
        "schedule_cron": str(backup_cfg.get("schedule_cron") or "").strip(),
        "timezone": str(timezone_name or "Asia/Kolkata").strip() or "Asia/Kolkata",
        "retention_days": _int_or_default(backup_cfg.get("retention_days"), 7),
    }
    next_run, validation_error = _next_run_info(normalized, normalized["timezone"])
    if not validation_error:
        try:
            validate_backup_config(normalized, normalized["timezone"])
        except ValueError as exc:
            validation_error = str(exc)
    normalized["schedule_display"] = f'{normalized["schedule_time"] or "-"} {normalized["timezone"]}' if normalized["schedule_time"] else 'Manual only'
    normalized["next_run"] = next_run
    normalized["validation_error"] = validation_error or ""
    return normalized


def _backup_destination_dir(backup_cfg: dict) -> Path:
    provider = str(backup_cfg.get("provider") or "filesystem").strip().lower() or "filesystem"
    if provider != "filesystem":
        raise ValueError("Only filesystem backup provider is supported right now.")
    destination = str(backup_cfg.get("destination") or "").strip()
    if not destination:
        raise ValueError("Backup destination is required.")
    return Path(destination)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest_from_archive(archive_path: Path) -> dict:
    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            member = tar.getmember("manifest.json")
            extracted = tar.extractfile(member)
            if extracted is None:
                raise ValueError("Backup manifest is missing.")
            return json.loads(extracted.read().decode("utf-8"))
    except KeyError as exc:
        raise ValueError("Backup manifest is missing.") from exc


def _manifest_summary(manifest: dict) -> dict:
    collections = manifest.get("collections") or []
    return {
        "provider": str(manifest.get("provider") or "filesystem"),
        "created_at": str(manifest.get("created_at") or "") or None,
        "db_name": str(manifest.get("db_name") or ""),
        "collections": len(collections),
        "documents": int(manifest.get("documents") or 0),
        "includes_uploads": bool(manifest.get("includes_uploads")),
        "retention_days": _int_or_default(manifest.get("retention_days"), 7),
    }


def _serialize_local_backup(*, archive_path: Path, manifest: dict | None, validation_error: str = "", linked_run: dict | None = None) -> dict:
    stat = archive_path.stat()
    summary = _manifest_summary(manifest or {}) if manifest else {}
    archive_name = archive_path.name
    linked = _serialize_run(linked_run) if linked_run else {}
    source = "filesystem"
    if linked:
        source = "both"
    return {
        "archive_name": archive_name,
        "archive_path": str(archive_path),
        "archive_size_bytes": int(stat.st_size),
        "created_at": summary.get("created_at") or _to_iso(datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)),
        "provider": summary.get("provider") or "filesystem",
        "db_name": summary.get("db_name") or db.name,
        "collections": int(summary.get("collections") or 0),
        "documents": int(summary.get("documents") or 0),
        "includes_uploads": bool(summary.get("includes_uploads")),
        "retention_days": int(summary.get("retention_days") or 0),
        "verified": not validation_error,
        "validation_error": validation_error,
        "sha256": _file_sha256(archive_path),
        "source": source,
        "linked_run": linked,
    }


def _backup_index_path(destination_dir: Path) -> Path:
    return destination_dir / BACKUP_INDEX_FILE


def _read_backup_index(destination_dir: Path) -> dict[str, dict]:
    index_path = _backup_index_path(destination_dir)
    if not index_path.exists():
        return {}
    try:
        raw = json.loads(index_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    rows = raw.get("backups") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        return {}
    mapped: dict[str, dict] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        key = str(item.get("archive_name") or "").strip()
        if key:
            mapped[key] = item
    return mapped


def _write_backup_index(destination_dir: Path, rows: list[dict]) -> None:
    destination_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": _to_iso(_now()),
        "backups": rows,
    }
    _backup_index_path(destination_dir).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _index_entry_from_local(local: dict, file_mtime: float) -> dict:
    return {
        "archive_name": str(local.get("archive_name") or ""),
        "archive_path": str(local.get("archive_path") or ""),
        "archive_size_bytes": int(local.get("archive_size_bytes") or 0),
        "created_at": local.get("created_at"),
        "provider": str(local.get("provider") or "filesystem"),
        "db_name": str(local.get("db_name") or db.name),
        "collections": int(local.get("collections") or 0),
        "documents": int(local.get("documents") or 0),
        "includes_uploads": bool(local.get("includes_uploads")),
        "retention_days": int(local.get("retention_days") or 0),
        "verified": bool(local.get("verified")),
        "validation_error": str(local.get("validation_error") or ""),
        "sha256": str(local.get("sha256") or ""),
        "file_mtime": float(file_mtime),
        "indexed_at": _to_iso(_now()),
    }


def _local_from_index_entry(entry: dict, linked_run: dict | None = None) -> dict:
    linked = _serialize_run(linked_run) if linked_run else {}
    source = "filesystem"
    if linked:
        source = "both"
    return {
        "archive_name": str(entry.get("archive_name") or ""),
        "archive_path": str(entry.get("archive_path") or ""),
        "archive_size_bytes": int(entry.get("archive_size_bytes") or 0),
        "created_at": entry.get("created_at"),
        "provider": str(entry.get("provider") or "filesystem"),
        "db_name": str(entry.get("db_name") or db.name),
        "collections": int(entry.get("collections") or 0),
        "documents": int(entry.get("documents") or 0),
        "includes_uploads": bool(entry.get("includes_uploads")),
        "retention_days": int(entry.get("retention_days") or 0),
        "verified": bool(entry.get("verified")),
        "validation_error": str(entry.get("validation_error") or ""),
        "sha256": str(entry.get("sha256") or ""),
        "source": source,
        "linked_run": linked,
    }


def _sync_backup_index(destination_dir: Path, rows: list[dict]) -> None:
    sanitized = []
    seen: set[str] = set()
    for item in rows:
        name = str(item.get("archive_name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        sanitized.append(item)
    sanitized.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    _write_backup_index(destination_dir, sanitized)


def _upsert_backup_index_entry(destination_dir: Path, entry: dict) -> None:
    rows = list(_read_backup_index(destination_dir).values())
    archive_name = str(entry.get("archive_name") or "").strip()
    rows = [item for item in rows if str(item.get("archive_name") or "").strip() != archive_name]
    rows.append(entry)
    _sync_backup_index(destination_dir, rows)


def _verify_archive_checksum(archive_path: Path, expected_sha256: str | None = None) -> str:
    actual_sha256 = _file_sha256(archive_path)
    if expected_sha256 and str(expected_sha256).strip() and actual_sha256 != str(expected_sha256).strip():
        raise ValueError("Backup checksum verification failed.")
    return actual_sha256


def _remove_backup_index_entry(destination_dir: Path, archive_name: str) -> None:
    rows = list(_read_backup_index(destination_dir).values())
    rows = [item for item in rows if str(item.get("archive_name") or "").strip() != str(archive_name or "").strip()]
    _sync_backup_index(destination_dir, rows)


def _delete_archive_file(archive_path: Path) -> bool:
    if not archive_path.exists() or not archive_path.is_file():
        return False
    archive_path.unlink()
    return True


def _serialize_run(doc: dict | None) -> dict:
    if not doc:
        return {}
    return {
        "id": str(doc.get("_id")),
        "status": str(doc.get("status") or "unknown"),
        "provider": str(doc.get("provider") or ""),
        "destination": str(doc.get("destination") or ""),
        "archive_name": str(doc.get("archive_name") or ""),
        "archive_path": str(doc.get("archive_path") or ""),
        "archive_size_bytes": int(doc.get("archive_size_bytes") or 0),
        "archive_sha256": str(doc.get("archive_sha256") or ""),
        "collections": int(doc.get("collections") or 0),
        "documents": int(doc.get("documents") or 0),
        "includes_uploads": bool(doc.get("includes_uploads")),
        "started_at": _to_iso(doc.get("started_at")),
        "completed_at": _to_iso(doc.get("completed_at")),
        "expires_at": _to_iso(doc.get("expires_at")),
        "error": str(doc.get("error") or ""),
        "manifest": doc.get("manifest") or {},
        "cleanup": doc.get("cleanup") or {},
        "last_restored_at": _to_iso(doc.get("last_restored_at")),
        "last_restore_status": str(doc.get("last_restore_status") or ""),
        "last_restore_error": str(doc.get("last_restore_error") or ""),
    }


async def _write_collection_dump(collection_name: str, target_dir: Path) -> tuple[int, int]:
    collection = db[collection_name]
    docs_path = target_dir / f"{collection_name}.ndjson"
    count = 0
    with docs_path.open("w", encoding="utf-8") as handle:
        async for item in collection.find({}).sort("_id", 1):
            handle.write(bson_dumps(item))
            handle.write("\n")
            count += 1
    size_bytes = docs_path.stat().st_size if docs_path.exists() else 0
    return count, size_bytes


async def _build_archive(*, destination_dir: Path, provider: str, retention_days: int) -> dict:
    timestamp = _now()
    stamp = timestamp.strftime("%Y%m%dT%H%M%SZ")
    archive_name = f"fintrack-backup-{stamp}-{_safe_slug(provider)}.tar.gz"
    archive_path = destination_dir / archive_name
    destination_dir.mkdir(parents=True, exist_ok=True)

    collection_names = [
        name for name in await db.list_collection_names()
        if not name.startswith("system.") and name not in EXCLUDED_COLLECTIONS
    ]
    collection_names.sort()

    total_documents = 0
    collections_meta: list[dict[str, Any]] = []
    includes_uploads = LOGO_UPLOAD_DIR.exists() and any(LOGO_UPLOAD_DIR.iterdir())

    with TemporaryDirectory(prefix="fintrack-backup-") as tmp_raw:
        tmp_dir = Path(tmp_raw)
        dump_dir = tmp_dir / "db"
        dump_dir.mkdir(parents=True, exist_ok=True)

        for name in collection_names:
            doc_count, size_bytes = await _write_collection_dump(name, dump_dir)
            total_documents += doc_count
            collections_meta.append({
                "name": name,
                "documents": doc_count,
                "size_bytes": size_bytes,
            })

        if includes_uploads:
            uploads_dir = tmp_dir / "uploads" / "logos"
            uploads_dir.mkdir(parents=True, exist_ok=True)
            for source in LOGO_UPLOAD_DIR.iterdir():
                if source.is_file():
                    (uploads_dir / source.name).write_bytes(source.read_bytes())

        manifest = {
            "created_at": timestamp.isoformat(),
            "provider": provider,
            "destination": str(destination_dir),
            "db_name": db.name,
            "collections": collections_meta,
            "documents": total_documents,
            "includes_uploads": includes_uploads,
            "uploads_path": str(LOGO_UPLOAD_DIR) if includes_uploads else "",
            "retention_days": retention_days,
        }
        (tmp_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(tmp_dir / "manifest.json", arcname="manifest.json")
            tar.add(dump_dir, arcname="db")
            if includes_uploads and (tmp_dir / "uploads").exists():
                tar.add(tmp_dir / "uploads", arcname="uploads")

    archive_size = archive_path.stat().st_size if archive_path.exists() else 0
    archive_sha256 = _file_sha256(archive_path) if archive_path.exists() else ""
    manifest["sha256"] = archive_sha256
    return {
        "archive_name": archive_name,
        "archive_path": str(archive_path),
        "archive_size_bytes": archive_size,
        "archive_sha256": archive_sha256,
        "collections": len(collection_names),
        "documents": total_documents,
        "includes_uploads": includes_uploads,
        "manifest": manifest,
        "expires_at": timestamp + timedelta(days=retention_days),
    }


async def cleanup_expired_backups(*, destination_dir: Path, retention_days: int) -> dict:
    cutoff = _now() - timedelta(days=retention_days)
    removed_files = 0
    removed_runs = 0

    cursor = db[BACKUP_COLLECTION].find({
        "status": "completed",
        "completed_at": {"$lt": cutoff},
    })
    async for run in cursor:
        archive_path = Path(str(run.get("archive_path") or "").strip())
        if archive_path.exists():
            try:
                archive_path.unlink()
                removed_files += 1
            except OSError:
                pass
        await db[BACKUP_COLLECTION].update_one(
            {"_id": run["_id"]},
            {"$set": {"status": "expired", "expired_at": _now()}},
        )
        removed_runs += 1

    if destination_dir.exists():
        for item in destination_dir.glob("fintrack-backup-*.tar.gz"):
            try:
                modified = datetime.fromtimestamp(item.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            if modified < cutoff:
                try:
                    item.unlink()
                    removed_files += 1
                except OSError:
                    pass

    return {"removed_files": removed_files, "expired_runs": removed_runs}


async def run_backup(*, actor: dict | None = None) -> dict:
    cfg = await get_admin_settings()
    backup_cfg = (cfg.get("backup") or {}).copy()
    timezone_name = str(((cfg.get("application") or {}).get("timezone") or "Asia/Kolkata")).strip() or "Asia/Kolkata"
    validate_backup_config(backup_cfg, timezone_name)
    provider = str(backup_cfg.get("provider") or "filesystem").strip().lower() or "filesystem"
    destination_dir = Path(str(backup_cfg.get("destination") or "").strip() or "/backups/fintrack")
    retention_days = _int_or_default(backup_cfg.get("retention_days"), 7)

    run_doc = {
        "status": "running",
        "provider": provider,
        "destination": str(destination_dir),
        "archive_name": "",
        "archive_path": "",
        "archive_size_bytes": 0,
        "collections": 0,
        "documents": 0,
        "includes_uploads": False,
        "started_at": _now(),
        "completed_at": None,
        "expires_at": None,
        "error": "",
        "manifest": {},
        "cleanup": {},
        "triggered_by": actor or {},
        "last_restored_at": None,
        "last_restore_status": "",
    }
    result = await db[BACKUP_COLLECTION].insert_one(run_doc)
    run_id = result.inserted_id

    try:
        archive = await _build_archive(
            destination_dir=destination_dir,
            provider=provider,
            retention_days=retention_days,
        )
        cleanup = await cleanup_expired_backups(destination_dir=destination_dir, retention_days=retention_days)
        await db[BACKUP_COLLECTION].update_one(
            {"_id": run_id},
            {
                "$set": {
                    **archive,
                    "status": "completed",
                    "completed_at": _now(),
                    "cleanup": cleanup,
                }
            },
        )
    except Exception as exc:
        await db[BACKUP_COLLECTION].update_one(
            {"_id": run_id},
            {
                "$set": {
                    "status": "failed",
                    "completed_at": _now(),
                    "error": str(exc),
                }
            },
        )
        raise

    final_doc = await db[BACKUP_COLLECTION].find_one({"_id": run_id})
    final_run = _serialize_run(final_doc)
    if final_doc and final_run.get("archive_path"):
        archive_path = Path(str(final_run.get("archive_path") or ""))
        local_entry = _serialize_local_backup(archive_path=archive_path, manifest=final_doc.get("manifest") or {}, linked_run=final_doc)
        _upsert_backup_index_entry(destination_dir, _index_entry_from_local(local_entry, archive_path.stat().st_mtime))
    return final_run


def _load_manifest(manifest_path: Path) -> dict:
    if not manifest_path.exists():
        raise ValueError("Backup manifest is missing.")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _collection_names_from_manifest(manifest: dict) -> list[str]:
    rows = manifest.get("collections") or []
    return [str(item.get("name") or "").strip() for item in rows if str(item.get("name") or "").strip()]


async def _restore_collection_from_file(collection_name: str, source_path: Path) -> int:
    docs = []
    if source_path.exists():
        for raw in source_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line:
                continue
            docs.append(bson_loads(line))

    collection = db[collection_name]
    await collection.delete_many({})
    if docs:
        await collection.insert_many(docs)
    return len(docs)


def _restore_uploads(extracted_root: Path, includes_uploads: bool) -> int:
    if not includes_uploads:
        return 0
    source_dir = extracted_root / "uploads" / "logos"
    if not source_dir.exists():
        return 0
    LOGO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for item in LOGO_UPLOAD_DIR.iterdir():
        if item.is_file():
            item.unlink()
    restored = 0
    for source in source_dir.iterdir():
        if source.is_file():
            shutil.copy2(source, LOGO_UPLOAD_DIR / source.name)
            restored += 1
    return restored


async def _restore_archive_path(*, archive_path: Path, actor: dict | None = None, create_safety_backup: bool = True, source_run_id: ObjectId | None = None, expected_sha256: str | None = None) -> dict:
    if not archive_path.exists():
        raise ValueError("Backup archive file is missing.")

    verified_sha256 = _verify_archive_checksum(archive_path, expected_sha256=expected_sha256)
    safety_backup = None
    try:
        if create_safety_backup:
            safety_backup = await run_backup(actor={**(actor or {}), "reason": "pre_restore_backup"})

        with TemporaryDirectory(prefix="fintrack-restore-") as tmp_raw:
            tmp_dir = Path(tmp_raw)
            with tarfile.open(archive_path, "r:gz") as tar:
                tar.extractall(tmp_dir)

            manifest = _load_manifest(tmp_dir / "manifest.json")
            collection_names = _collection_names_from_manifest(manifest)
            restored_documents = 0
            restored_collections = 0
            for name in collection_names:
                source_file = tmp_dir / "db" / f"{name}.ndjson"
                restored_documents += await _restore_collection_from_file(name, source_file)
                restored_collections += 1

            restored_uploads = _restore_uploads(tmp_dir, bool(manifest.get("includes_uploads")))

        restored_at = _now()
        if source_run_id is not None:
            await db[BACKUP_COLLECTION].update_one(
                {"_id": source_run_id},
                {
                    "$set": {
                        "last_restored_at": restored_at,
                        "last_restore_status": "completed",
                        "last_restore_error": "",
                        "last_restored_by": actor or {},
                    }
                },
            )
        source_doc = await db[BACKUP_COLLECTION].find_one({"_id": source_run_id}) if source_run_id is not None else None
        return {
            "source_backup": _serialize_run(source_doc),
            "source_file": {**_serialize_local_backup(archive_path=archive_path, manifest=manifest), "sha256": verified_sha256},
            "restored_at": _to_iso(restored_at),
            "collections": restored_collections,
            "documents": restored_documents,
            "uploads": restored_uploads,
            "safety_backup": safety_backup or {},
        }
    except Exception as exc:
        if source_run_id is not None:
            await db[BACKUP_COLLECTION].update_one(
                {"_id": source_run_id},
                {"$set": {"last_restore_status": "failed", "last_restore_error": str(exc)}}
            )
        raise


async def restore_backup(*, run_id: str, actor: dict | None = None, create_safety_backup: bool = True) -> dict:
    if not ObjectId.is_valid(run_id):
        raise ValueError("Invalid backup id.")
    source_id = ObjectId(run_id)
    source = await db[BACKUP_COLLECTION].find_one({"_id": source_id})
    if not source:
        raise ValueError("Backup not found.")
    if str(source.get("status") or "") not in {"completed", "expired"}:
        raise ValueError("Only completed backups can be restored.")

    archive_path = Path(str(source.get("archive_path") or "").strip())
    expected_sha256 = str(((source.get("manifest") or {}).get("sha256") or "")).strip()
    if not expected_sha256:
        expected_sha256 = str(source.get("archive_sha256") or "").strip()
    return await _restore_archive_path(
        archive_path=archive_path,
        actor=actor,
        create_safety_backup=create_safety_backup,
        source_run_id=source_id,
        expected_sha256=expected_sha256 or None,
    )


async def get_backup_status() -> dict:
    cfg = await get_admin_settings()
    backup_cfg = (cfg.get("backup") or {}).copy()
    app_cfg = (cfg.get("application") or {}).copy()
    timezone_name = str(app_cfg.get("timezone") or "Asia/Kolkata").strip() or "Asia/Kolkata"
    latest = await db[BACKUP_COLLECTION].find_one(sort=[("started_at", -1)])
    return {
        "config": describe_backup_config(backup_cfg, timezone_name),
        "last_run": _serialize_run(latest),
        "checked_at": _to_iso(_now()),
    }


async def list_backup_history(limit: int = 10) -> list[dict]:
    rows = []
    cursor = db[BACKUP_COLLECTION].find({}).sort("started_at", -1).limit(max(1, int(limit)))
    async for item in cursor:
        rows.append(_serialize_run(item))
    return rows


async def list_local_backups(limit: int = 20, backup_cfg: dict | None = None) -> list[dict]:
    if backup_cfg is None:
        cfg = await get_admin_settings()
        backup_cfg = (cfg.get("backup") or {}).copy()
    else:
        backup_cfg = (backup_cfg or {}).copy()
    destination_dir = _backup_destination_dir(backup_cfg)
    if not destination_dir.exists() or not destination_dir.is_dir():
        return []

    run_lookup: dict[str, dict] = {}
    try:
        cursor = db[BACKUP_COLLECTION].find({}).sort("started_at", -1).limit(max(20, int(limit) * 3))
        async for item in cursor:
            archive_name = str(item.get("archive_name") or "").strip()
            archive_path = str(item.get("archive_path") or "").strip()
            if archive_name and archive_name not in run_lookup:
                run_lookup[archive_name] = item
            if archive_path and archive_path not in run_lookup:
                run_lookup[archive_path] = item
    except Exception:
        run_lookup = {}

    indexed = _read_backup_index(destination_dir)
    refreshed_index: list[dict] = []
    rows = []
    files = sorted(destination_dir.glob("fintrack-backup-*.tar.gz"), key=lambda item: item.stat().st_mtime, reverse=True)
    for archive_path in files[: max(1, int(limit))]:
        stat = archive_path.stat()
        linked_run = run_lookup.get(archive_path.name) or run_lookup.get(str(archive_path))
        cached = indexed.get(archive_path.name)
        if cached and int(cached.get("archive_size_bytes") or 0) == int(stat.st_size) and float(cached.get("file_mtime") or 0) == float(stat.st_mtime):
            rows.append(_local_from_index_entry(cached, linked_run=linked_run))
            refreshed_index.append(cached)
            continue

        manifest = None
        validation_error = ""
        try:
            manifest = _load_manifest_from_archive(archive_path)
        except Exception as exc:
            validation_error = str(exc)
        local = _serialize_local_backup(
            archive_path=archive_path,
            manifest=manifest,
            validation_error=validation_error,
            linked_run=linked_run,
        )
        rows.append(local)
        refreshed_index.append(_index_entry_from_local(local, stat.st_mtime))

    _sync_backup_index(destination_dir, refreshed_index)
    return rows


async def verify_local_backup(*, archive_name: str, backup_cfg: dict | None = None) -> dict:
    if backup_cfg is None:
        cfg = await get_admin_settings()
        backup_cfg = (cfg.get("backup") or {}).copy()
    else:
        backup_cfg = (backup_cfg or {}).copy()
    destination_dir = _backup_destination_dir(backup_cfg)
    archive_file = Path(str(archive_name or "").strip()).name
    if not archive_file:
        raise ValueError("Backup file is required.")
    archive_path = destination_dir / archive_file
    if not archive_path.exists() or not archive_path.is_file():
        raise ValueError("Selected backup file was not found in the configured destination.")

    linked_run = None
    try:
        linked_run = await db[BACKUP_COLLECTION].find_one({"archive_name": archive_file})
    except Exception:
        linked_run = None

    validation_error = ""
    manifest = None
    try:
        manifest = _load_manifest_from_archive(archive_path)
        checksum = _verify_archive_checksum(archive_path)
        local = _serialize_local_backup(archive_path=archive_path, manifest=manifest, linked_run=linked_run)
        local["sha256"] = checksum
    except Exception as exc:
        validation_error = str(exc)
        local = _serialize_local_backup(archive_path=archive_path, manifest=manifest, validation_error=validation_error, linked_run=linked_run)

    _upsert_backup_index_entry(destination_dir, _index_entry_from_local(local, archive_path.stat().st_mtime))
    return local


async def delete_backup(*, run_id: str) -> dict:
    if not ObjectId.is_valid(run_id):
        raise ValueError("Invalid backup id.")
    source_id = ObjectId(run_id)
    source = await db[BACKUP_COLLECTION].find_one({"_id": source_id})
    if not source:
        raise ValueError("Backup not found.")

    archive_name = str(source.get("archive_name") or "").strip()
    archive_path = Path(str(source.get("archive_path") or "").strip())
    destination_dir = archive_path.parent if str(archive_path) else None
    deleted_file = False
    if destination_dir and archive_name:
        _remove_backup_index_entry(destination_dir, archive_name)
    if str(archive_path):
        deleted_file = _delete_archive_file(archive_path)

    await db[BACKUP_COLLECTION].delete_one({"_id": source_id})
    return {
        "backup_id": run_id,
        "archive_name": archive_name,
        "deleted_file": deleted_file,
        "deleted_history": True,
    }


async def delete_backup_file(*, archive_name: str, backup_cfg: dict | None = None) -> dict:
    if backup_cfg is None:
        cfg = await get_admin_settings()
        backup_cfg = (cfg.get("backup") or {}).copy()
    else:
        backup_cfg = (backup_cfg or {}).copy()
    destination_dir = _backup_destination_dir(backup_cfg)
    archive_file = Path(str(archive_name or "").strip()).name
    if not archive_file:
        raise ValueError("Backup file is required.")
    archive_path = destination_dir / archive_file
    deleted_file = _delete_archive_file(archive_path)
    _remove_backup_index_entry(destination_dir, archive_file)

    deleted_history = False
    try:
        result = await db[BACKUP_COLLECTION].delete_many({"archive_name": archive_file})
        deleted_history = bool(result.deleted_count)
    except Exception:
        deleted_history = False

    return {
        "archive_name": archive_file,
        "deleted_file": deleted_file,
        "deleted_history": deleted_history,
    }


async def restore_backup_file(*, archive_name: str, actor: dict | None = None, create_safety_backup: bool = True) -> dict:
    cfg = await get_admin_settings()
    backup_cfg = (cfg.get("backup") or {}).copy()
    destination_dir = _backup_destination_dir(backup_cfg)
    archive_file = Path(str(archive_name or "").strip()).name
    if not archive_file:
        raise ValueError("Backup file is required.")
    archive_path = destination_dir / archive_file
    if not archive_path.exists() or not archive_path.is_file():
        raise ValueError("Selected backup file was not found in the configured destination.")

    source_run_id = None
    try:
        linked = await db[BACKUP_COLLECTION].find_one({"archive_name": archive_file})
        if linked and ObjectId.is_valid(str(linked.get("_id") or "")):
            source_run_id = linked.get("_id")
    except Exception:
        linked = None
        source_run_id = None

    indexed = _read_backup_index(destination_dir).get(archive_file) or {}
    expected_sha256 = str(indexed.get("sha256") or "").strip()
    if not expected_sha256 and linked:
        expected_sha256 = str(((linked.get("manifest") or {}).get("sha256") or linked.get("archive_sha256") or "")).strip()

    return await _restore_archive_path(
        archive_path=archive_path,
        actor=actor,
        create_safety_backup=create_safety_backup,
        source_run_id=source_run_id,
        expected_sha256=expected_sha256 or None,
    )
