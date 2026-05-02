"""UI-triggered dictionary and frequency imports."""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.common import constants
from app.db.database import get_db_session
from app.db.models import DictionaryImportRun, VocabuildaryUser, Word

logger = logging.getLogger(__name__)

RUNNING_STATUSES = ("queued", "running")
_IMPORT_LOCK = threading.Lock()


class ImportValidationError(ValueError):
    """Raised when a UI import request is malformed."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_positive_int(value: Any, default: int, minimum: int = 1, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _iso_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _progress_percent(run: DictionaryImportRun) -> float:
    if not run.total_items:
        return 0.0
    return round(min(100.0, (run.processed_items / run.total_items) * 100.0), 1)


def serialize_import_run(run: DictionaryImportRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "source": run.source,
        "language_code": run.language_code,
        "status": run.status,
        "chunk_index": run.chunk_index,
        "chunk_count": run.chunk_count,
        "total_items": run.total_items,
        "processed_items": run.processed_items,
        "inserted_items": run.inserted_items,
        "updated_items": run.updated_items,
        "skipped_items": run.skipped_items,
        "error_message": run.error_message,
        "params": run.params or {},
        "progress_percent": _progress_percent(run),
        "started_at": _iso_datetime(run.started_at),
        "finished_at": _iso_datetime(run.finished_at),
        "created_at": _iso_datetime(run.created_at),
        "updated_at": _iso_datetime(run.updated_at),
    }


def get_dictionary_stats(db: Session, language_code: str = "en") -> dict[str, Any]:
    base = select(func.count()).select_from(Word).where(Word.language_code == language_code)
    total_words = db.execute(base).scalar_one()
    frequency_words = db.execute(
        base.where(Word.frequency_source.is_not(None))
    ).scalar_one()
    defined_words = db.execute(
        base.where(Word.meaning != "")
    ).scalar_one()
    frequency_ranked_words = db.execute(
        base.where(Word.frequency_rank.is_not(None))
    ).scalar_one()
    top_rank = db.execute(
        select(func.max(Word.frequency_rank)).where(
            Word.language_code == language_code,
            Word.frequency_rank.is_not(None),
        )
    ).scalar_one()

    return {
        "language_code": language_code,
        "total_words": int(total_words or 0),
        "frequency_words": int(frequency_words or 0),
        "frequency_ranked_words": int(frequency_ranked_words or 0),
        "defined_words": int(defined_words or 0),
        "max_frequency_rank": int(top_rank) if top_rank is not None else None,
    }


def list_import_runs(db: Session, limit: int = 20) -> list[DictionaryImportRun]:
    stmt = (
        select(DictionaryImportRun)
        .order_by(DictionaryImportRun.created_at.desc(), DictionaryImportRun.id.desc())
        .limit(max(1, min(int(limit or 20), 100)))
    )
    return list(db.execute(stmt).scalars())


def get_active_import_run(db: Session) -> DictionaryImportRun | None:
    stmt = (
        select(DictionaryImportRun)
        .where(DictionaryImportRun.status.in_(RUNNING_STATUSES))
        .order_by(DictionaryImportRun.created_at.asc(), DictionaryImportRun.id.asc())
        .limit(1)
    )
    return db.execute(stmt).scalar_one_or_none()


def mark_stale_import_runs_failed() -> int:
    """Mark in-flight imports from a previous pod process as failed."""
    db = get_db_session()
    try:
        result = db.execute(
            update(DictionaryImportRun)
            .where(DictionaryImportRun.status.in_(RUNNING_STATUSES))
            .values(
                status="failed",
                error_message="Import was interrupted by a service restart.",
                finished_at=_utc_now(),
                updated_at=_utc_now(),
            )
        )
        db.commit()
        return int(result.rowcount or 0)
    finally:
        db.close()


def start_frequency_import(
    db: Session,
    user: VocabuildaryUser,
    payload: dict[str, Any] | None = None,
) -> tuple[DictionaryImportRun, bool]:
    payload = payload or {}
    active_run = get_active_import_run(db)
    if active_run is not None:
        return active_run, False

    language_code = str(payload.get("language_code") or "en").strip().lower() or "en"
    wordlist = str(payload.get("wordlist") or constants.FREQUENCY_IMPORT_WORDLIST).strip() or "best"
    max_words = _as_positive_int(
        payload.get("max_words"),
        constants.FREQUENCY_IMPORT_MAX_WORDS,
        minimum=1,
        maximum=5_000_000,
    )
    batch_size = _as_positive_int(
        payload.get("batch_size"),
        constants.FREQUENCY_IMPORT_BATCH_SIZE,
        minimum=100,
        maximum=10_000,
    )

    run = DictionaryImportRun(
        source="wordfreq",
        language_code=language_code,
        status="queued",
        total_items=max_words,
        started_by_user_id=user.id,
        params={
            "wordlist": wordlist,
            "max_words": max_words,
            "batch_size": batch_size,
        },
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    _spawn_import_thread(
        run.id,
        _run_frequency_import,
        language_code=language_code,
        wordlist=wordlist,
        max_words=max_words,
        batch_size=batch_size,
    )
    return run, True


def start_kaikki_import(
    db: Session,
    user: VocabuildaryUser,
    payload: dict[str, Any] | None = None,
) -> tuple[DictionaryImportRun, bool]:
    payload = payload or {}
    active_run = get_active_import_run(db)
    if active_run is not None:
        return active_run, False

    language_code = str(payload.get("language_code") or "en").strip().lower() or "en"
    chunk_count = _as_positive_int(
        payload.get("chunk_count"),
        constants.KAIKKI_IMPORT_CHUNK_COUNT,
        minimum=1,
        maximum=100,
    )
    chunk_index = _as_positive_int(payload.get("chunk_index"), 1, minimum=1, maximum=chunk_count)
    total_estimate = _as_positive_int(
        payload.get("total_estimate"),
        constants.KAIKKI_IMPORT_TOTAL_ESTIMATE,
        minimum=1,
        maximum=20_000_000,
    )
    batch_size = _as_positive_int(
        payload.get("batch_size"),
        constants.KAIKKI_IMPORT_BATCH_SIZE,
        minimum=50,
        maximum=5_000,
    )
    insert_missing = bool(payload.get("insert_missing", False))
    source_url = str(payload.get("source_url") or constants.KAIKKI_ENGLISH_JSONL_URL).strip()
    if not source_url:
        raise ImportValidationError("Kaikki source URL is required.")

    start_offset = int(total_estimate * (chunk_index - 1) / chunk_count)
    end_offset = int(total_estimate * chunk_index / chunk_count)
    total_items = end_offset - start_offset

    run = DictionaryImportRun(
        source="kaikki",
        language_code=language_code,
        status="queued",
        chunk_index=chunk_index,
        chunk_count=chunk_count,
        total_items=total_items,
        started_by_user_id=user.id,
        params={
            "source_url": source_url,
            "insert_missing": insert_missing,
            "start_offset": start_offset,
            "end_offset": end_offset,
            "total_estimate": total_estimate,
            "batch_size": batch_size,
        },
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    _spawn_import_thread(
        run.id,
        _run_kaikki_import,
        language_code=language_code,
        source_url=source_url,
        chunk_index=chunk_index,
        chunk_count=chunk_count,
        start_offset=start_offset,
        end_offset=end_offset,
        batch_size=batch_size,
        insert_missing=insert_missing,
    )
    return run, True


def _spawn_import_thread(
    run_id: int,
    target: Callable[..., None],
    **kwargs: Any,
) -> None:
    thread = threading.Thread(
        target=_import_thread_entrypoint,
        args=(run_id, target, kwargs),
        name=f"dictionary-import-{run_id}",
        daemon=True,
    )
    thread.start()


def _import_thread_entrypoint(
    run_id: int,
    target: Callable[..., None],
    kwargs: dict[str, Any],
) -> None:
    if not _IMPORT_LOCK.acquire(blocking=False):
        _finish_run(
            run_id,
            status="failed",
            error_message="Another dictionary import is already running in this pod.",
        )
        return

    try:
        target(run_id, **kwargs)
    except Exception as exc:
        logger.error("Dictionary import run %s failed: %s", run_id, exc, exc_info=True)
        _finish_run(run_id, status="failed", error_message=str(exc))
    finally:
        _IMPORT_LOCK.release()


def _patch_run(run_id: int, **values: Any) -> None:
    values["updated_at"] = _utc_now()
    db = get_db_session()
    try:
        db.execute(update(DictionaryImportRun).where(DictionaryImportRun.id == run_id).values(**values))
        db.commit()
    finally:
        db.close()


def _finish_run(run_id: int, status: str, error_message: str | None = None) -> None:
    _patch_run(
        run_id,
        status=status,
        error_message=error_message,
        finished_at=_utc_now(),
    )


def _run_frequency_import(
    run_id: int,
    language_code: str,
    wordlist: str,
    max_words: int,
    batch_size: int,
) -> None:
    _patch_run(run_id, status="running", started_at=_utc_now(), error_message=None)

    try:
        from wordfreq import top_n_list, word_frequency, zipf_frequency
    except ImportError as exc:
        raise RuntimeError("The wordfreq package is not installed in this image.") from exc

    words = top_n_list(language_code, max_words, wordlist=wordlist)
    total_items = len(words)
    _patch_run(run_id, total_items=total_items)

    inserted = 0
    updated = 0
    skipped = 0
    processed = 0

    for start in range(0, total_items, batch_size):
        batch_words = words[start : start + batch_size]
        rows: list[dict[str, Any]] = []
        for rank, word in enumerate(batch_words, start=start + 1):
            normalized_word = str(word).strip()
            if not _looks_like_word(normalized_word):
                skipped += 1
                continue
            rows.append(
                {
                    "language_code": language_code,
                    "word": normalized_word,
                    "meaning": "",
                    "example": "",
                    "frequency_rank": rank,
                    "frequency_score": float(word_frequency(normalized_word, language_code)),
                    "zipf_frequency": float(zipf_frequency(normalized_word, language_code)),
                    "frequency_source": "wordfreq",
                    "frequency_updated_at": _utc_now(),
                    "metadata": {
                        "frequency": {
                            "source": "wordfreq",
                            "wordlist": wordlist,
                        }
                    },
                    "sent": False,
                }
            )

        batch_inserted, batch_updated = _upsert_frequency_rows(rows, language_code)
        inserted += batch_inserted
        updated += batch_updated
        processed += len(batch_words)
        _patch_run(
            run_id,
            processed_items=processed,
            inserted_items=inserted,
            updated_items=updated,
            skipped_items=skipped,
        )

    _finish_run(run_id, status="completed")


def _upsert_frequency_rows(rows: list[dict[str, Any]], language_code: str) -> tuple[int, int]:
    if not rows:
        return 0, 0

    rows = [_normalize_word_upsert_row(row) for row in rows]
    words = [row["word"] for row in rows]
    db = get_db_session()
    try:
        existing_words = set(
            db.execute(
                select(Word.word).where(
                    Word.language_code == language_code,
                    Word.word.in_(words),
                )
            ).scalars()
        )
        stmt = pg_insert(Word).values(rows)
        excluded = stmt.excluded
        stmt = stmt.on_conflict_do_update(
            index_elements=["language_code", "word"],
            set_={
                "frequency_rank": excluded.frequency_rank,
                "frequency_score": excluded.frequency_score,
                "zipf_frequency": excluded.zipf_frequency,
                "frequency_source": excluded.frequency_source,
                "frequency_updated_at": excluded.frequency_updated_at,
            },
        )
        db.execute(stmt)
        db.commit()
    finally:
        db.close()

    inserted = sum(1 for row in rows if row["word"] not in existing_words)
    return inserted, len(rows) - inserted


def _run_kaikki_import(
    run_id: int,
    language_code: str,
    source_url: str,
    chunk_index: int,
    chunk_count: int,
    start_offset: int,
    end_offset: int,
    batch_size: int,
    insert_missing: bool,
) -> None:
    _patch_run(run_id, status="running", started_at=_utc_now(), error_message=None)

    inserted = 0
    updated = 0
    skipped = 0
    processed = 0
    batch: list[dict[str, Any]] = []
    timeout = httpx.Timeout(constants.KAIKKI_IMPORT_TIMEOUT_SECONDS, connect=30.0)

    with httpx.stream("GET", source_url, follow_redirects=True, timeout=timeout) as response:
        response.raise_for_status()
        for zero_index, line in enumerate(response.iter_lines()):
            if zero_index < start_offset:
                continue
            if zero_index >= end_offset and chunk_index < chunk_count:
                break

            processed += 1
            row = _kaikki_line_to_word_row(line, language_code, source_url)
            if row is None:
                skipped += 1
            else:
                batch.append(row)

            if len(batch) >= batch_size:
                batch_inserted, batch_updated, batch_skipped = _upsert_definition_rows(
                    batch,
                    language_code=language_code,
                    insert_missing=insert_missing,
                )
                inserted += batch_inserted
                updated += batch_updated
                skipped += batch_skipped
                batch = []
                _patch_run(
                    run_id,
                    processed_items=processed,
                    inserted_items=inserted,
                    updated_items=updated,
                    skipped_items=skipped,
                )

    if batch:
        batch_inserted, batch_updated, batch_skipped = _upsert_definition_rows(
            batch,
            language_code=language_code,
            insert_missing=insert_missing,
        )
        inserted += batch_inserted
        updated += batch_updated
        skipped += batch_skipped

    _patch_run(
        run_id,
        processed_items=processed,
        inserted_items=inserted,
        updated_items=updated,
        skipped_items=skipped,
    )
    _finish_run(run_id, status="completed")


def _kaikki_line_to_word_row(
    line: str,
    language_code: str,
    source_url: str,
) -> dict[str, Any] | None:
    if not line:
        return None
    try:
        item = json.loads(line)
    except json.JSONDecodeError:
        return None

    item_language_code = str(item.get("lang_code") or language_code).lower()
    if item_language_code != language_code:
        return None

    word = str(item.get("word") or "").strip()
    if not _looks_like_word(word):
        return None

    meaning = _first_gloss(item)
    example = _first_example(item)
    pronunciation = _first_pronunciation(item)
    etymology = item.get("etymology_text")
    if isinstance(etymology, list):
        etymology = "\n".join(str(part) for part in etymology if part)
    if etymology is not None:
        etymology = str(etymology).strip()

    return {
        "language_code": language_code,
        "word": word,
        "meaning": meaning or "",
        "example": example or "",
        "part_of_speech": str(item.get("pos") or "").strip() or None,
        "pronunciation": pronunciation,
        "etymology": etymology or None,
        "definition_source": "kaikki",
        "definition_updated_at": _utc_now(),
        "metadata": {
            "definition": {
                "source": "kaikki",
                "url": source_url,
            }
        },
        "sent": False,
    }


def _first_gloss(item: dict[str, Any]) -> str | None:
    for sense in _iter_senses(item):
        for key in ("glosses", "raw_glosses"):
            value = sense.get(key)
            if isinstance(value, list):
                for gloss in value:
                    text = str(gloss or "").strip()
                    if text:
                        return text
            elif isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _looks_like_word(value: str) -> bool:
    return bool(value and any(character.isalpha() for character in value))


def _first_example(item: dict[str, Any]) -> str | None:
    for sense in _iter_senses(item):
        examples = sense.get("examples")
        if not isinstance(examples, list):
            continue
        for example in examples:
            if isinstance(example, dict):
                text = str(example.get("text") or "").strip()
            else:
                text = str(example or "").strip()
            if text:
                return text
    return None


def _first_pronunciation(item: dict[str, Any]) -> str | None:
    sounds = item.get("sounds")
    if not isinstance(sounds, list):
        return None
    for sound in sounds:
        if not isinstance(sound, dict):
            continue
        for key in ("ipa", "enpr"):
            value = str(sound.get(key) or "").strip()
            if value:
                return value
    return None


def _iter_senses(item: dict[str, Any]) -> Iterable[dict[str, Any]]:
    senses = item.get("senses")
    if not isinstance(senses, list):
        return []
    return (sense for sense in senses if isinstance(sense, dict))


def _dedupe_rows_by_word(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        word = row["word"]
        existing = merged.get(word)
        if existing is None:
            merged[word] = row
            continue
        for key in ("meaning", "example", "part_of_speech", "pronunciation", "etymology"):
            if not existing.get(key) and row.get(key):
                existing[key] = row[key]
    return list(merged.values())


def _upsert_definition_rows(
    rows: list[dict[str, Any]],
    language_code: str,
    insert_missing: bool,
) -> tuple[int, int, int]:
    rows = _dedupe_rows_by_word(rows)
    if not rows:
        return 0, 0, 0

    rows = [_normalize_word_upsert_row(row) for row in rows]
    words = [row["word"] for row in rows]
    db = get_db_session()
    try:
        existing_words = set(
            db.execute(
                select(Word.word).where(
                    Word.language_code == language_code,
                    Word.word.in_(words),
                )
            ).scalars()
        )

        if not insert_missing:
            rows = [row for row in rows if row["word"] in existing_words]
        skipped = len(words) - len(rows)
        if not rows:
            db.rollback()
            return 0, 0, skipped

        stmt = pg_insert(Word).values(rows)
        excluded = stmt.excluded
        stmt = stmt.on_conflict_do_update(
            index_elements=["language_code", "word"],
            set_={
                "meaning": _fill_if_empty(Word.meaning, excluded.meaning),
                "example": _fill_if_empty(Word.example, excluded.example),
                "part_of_speech": _fill_if_empty(Word.part_of_speech, excluded.part_of_speech),
                "pronunciation": _fill_if_empty(Word.pronunciation, excluded.pronunciation),
                "etymology": _fill_if_empty(Word.etymology, excluded.etymology),
                "definition_source": _fill_if_empty(Word.definition_source, excluded.definition_source),
                "definition_updated_at": case(
                    (
                        and_(
                            or_(Word.meaning.is_(None), Word.meaning == ""),
                            excluded.meaning != "",
                        ),
                        excluded.definition_updated_at,
                    ),
                    else_=Word.definition_updated_at,
                ),
            },
        )
        db.execute(stmt)
        db.commit()
    finally:
        db.close()

    inserted = sum(1 for row in rows if row["word"] not in existing_words)
    return inserted, len(rows) - inserted, skipped


def _fill_if_empty(existing_col: Any, excluded_col: Any) -> Any:
    return case(
        (
            and_(
                or_(existing_col.is_(None), existing_col == ""),
                excluded_col.is_not(None),
                excluded_col != "",
            ),
            excluded_col,
        ),
        else_=existing_col,
    )


def _normalize_word_upsert_row(row: dict[str, Any]) -> dict[str, Any]:
    """Map external payload keys to ORM attribute names for Word upserts."""
    if "metadata" not in row or "word_metadata" in row:
        return row
    normalized = dict(row)
    normalized["word_metadata"] = normalized.pop("metadata")
    return normalized
