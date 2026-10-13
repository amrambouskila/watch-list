"""Committed import fixtures backed by disposable media and real PostgreSQL."""

from __future__ import annotations

import uuid
from datetime import date
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tv_watchlist.config import Settings
from tv_watchlist.data.enums import MediaImportIdentifiedBy, MediaImportSource, MediaImportStatus, MediaType
from tv_watchlist.data.models import MediaImport, MediaImportOperation, Title
from tv_watchlist.data.session import build_session_factory


class ImportMoveFixture:
    def __init__(self, engine: AsyncEngine, root: Path) -> None:
        self.factory: async_sessionmaker[AsyncSession] = build_session_factory(engine)
        self.settings = Settings(
            _env_file=None, import_staging_dir=root / "staging", media_root=root / "media", library_dir=root / "unused"
        )
        self.staging = root / "staging"
        self.media = root / "media"
        self.staging.mkdir()
        self.media.mkdir()
        self.ids: list[uuid.UUID] = []
        self.titles: list[uuid.UUID] = []

    async def seed(self, name: str = "Film", content: bytes = b"abc") -> MediaImport:
        source = self.staging / f"{uuid.uuid4()}.mkv"
        source.write_bytes(content)
        async with self.factory() as session:
            title = Title(
                media_type=MediaType.MOVIE, name=name, match_key=name.lower(), first_air_date=date(2020, 1, 1)
            )
            session.add(title)
            await session.flush()
            self.titles.append(title.id)
            row = MediaImport(
                title_id=title.id,
                source=MediaImportSource.STAGING_FOLDER,
                source_path=str(source),
                original_name=source.name,
                size_bytes=len(content),
                status=MediaImportStatus.IDENTIFIED,
                identified_by=MediaImportIdentifiedBy.FILENAME,
                identification_confidence=1.0,
            )
            session.add(row)
            await session.commit()
            self.ids.append(row.id)
            return row

    async def operation(self, import_id: uuid.UUID) -> MediaImportOperation:
        async with self.factory() as session:
            return (
                await session.scalars(
                    select(MediaImportOperation)
                    .where(MediaImportOperation.media_import_id == import_id)
                    .order_by(MediaImportOperation.created_at.desc())
                )
            ).one()

    async def close(self) -> None:
        async with self.factory() as session:
            await session.execute(
                delete(MediaImportOperation).where(MediaImportOperation.media_import_id.in_(self.ids))
            )
            for row in (await session.scalars(select(MediaImport).where(MediaImport.id.in_(self.ids)))).all():
                row.superseded_at = None
                row.superseded_by_id = None
            await session.flush()
            await session.execute(delete(MediaImport).where(MediaImport.id.in_(self.ids)))
            await session.execute(delete(Title).where(Title.id.in_(self.titles)))
            await session.commit()
