"""Filesystem side of a durable import, called only from worker threads."""

from __future__ import annotations

import os
import shutil
import stat
import sys
import uuid
from pathlib import Path, PurePosixPath

from tv_watchlist.clock import utcnow
from tv_watchlist.config import Settings
from tv_watchlist.constants import (
    BACKUP_TIMESTAMP_FORMAT,
    IMPORT_COPY_CHUNK_BYTES,
    MEDIA_IMPORT_SUPERSEDED_DIRNAME,
    MEDIA_IMPORT_TEMP_PREFIX,
)
from tv_watchlist.data.enums import MediaImportOperationPhase
from tv_watchlist.data.errors import ImportPathError
from tv_watchlist.data.models import Episode, MediaImport, MediaImportOperation, Title
from tv_watchlist.models.import_file_identity import ImportFileIdentity
from tv_watchlist.services.file_digest import sha256_of
from tv_watchlist.services.import_naming import assert_within, plan_destination
from tv_watchlist.services.rename_exclusive import rename_exclusive


class ImportFiles:
    """Validate the journal against real artifacts before each filesystem transition."""

    def __init__(self, settings: Settings, operation: MediaImportOperation) -> None:
        self.settings = settings
        self.operation = operation
        if settings.import_staging_dir is None or settings.media_root is None:
            raise ImportPathError("Import roots are not configured")
        self.staging = settings.import_staging_dir.resolve()
        self.media = settings.media_root.resolve()
        if str(self.staging) != operation.staging_root or str(self.media) != operation.media_root:
            raise ImportPathError("Configured import roots changed; recovery needs owner review")
        self.source = self._path(operation.source_path, self.staging)
        self.destination = self._path(operation.destination_path, self.media)
        self.temp = self._path(operation.temp_path, self.media)
        self.archive = None if operation.superseded_path is None else self._path(operation.superseded_path, self.media)
        self.source_identity = ImportFileIdentity.model_validate(operation.source_identity)
        self.previous_identity = (
            None
            if operation.destination_identity is None
            else ImportFileIdentity.model_validate(operation.destination_identity)
        )
        self.temp_identity = (
            None if operation.temp_identity is None else ImportFileIdentity.model_validate(operation.temp_identity)
        )

    @classmethod
    def prepare(
        cls, settings: Settings, row: MediaImport, title: Title, episode: Episode | None
    ) -> MediaImportOperation:
        """Read stable source/destination snapshots without mutating either filesystem."""
        if settings.import_staging_dir is None or settings.media_root is None:
            raise ImportPathError("Import roots are not configured")
        staging, media = settings.import_staging_dir.resolve(), settings.media_root.resolve()
        source = assert_within(Path(row.source_path), staging)
        cls._path(Path(row.source_path).relative_to(staging).as_posix(), staging)
        plan = plan_destination(media, title, episode, source.suffix)
        destination = cls._path(plan.relative_path.as_posix(), media)
        identity = cls._identity(source)
        if identity is None or identity.size_bytes != row.size_bytes:
            raise OSError("Staging source is missing or its size changed")
        digest = sha256_of(source)
        previous = cls._identity(destination)
        previous_digest = None if previous is None else sha256_of(destination)
        identifier = uuid.uuid4()
        archive = (
            None
            if previous is None
            else PurePosixPath(
                MEDIA_IMPORT_SUPERSEDED_DIRNAME,
                f"{utcnow().strftime(BACKUP_TIMESTAMP_FORMAT)}-{identifier.hex}",
                plan.relative_path,
            ).as_posix()
        )
        operation = MediaImportOperation(
            id=identifier,
            media_import_id=row.id,
            phase=MediaImportOperationPhase.PREPARED,
            staging_root=str(staging),
            media_root=str(media),
            source_path=source.relative_to(staging).as_posix(),
            destination_path=plan.relative_path.as_posix(),
            temp_path=plan.relative_path.with_name(f"{MEDIA_IMPORT_TEMP_PREFIX}{identifier.hex}.part").as_posix(),
            superseded_path=archive,
            source_identity=identity.model_dump(),
            source_sha256=digest,
            destination_identity=None if previous is None else previous.model_dump(),
            destination_sha256=previous_digest,
        )
        cls(settings, operation).verify_source()
        return operation

    @staticmethod
    def _path(relative: str, root: Path) -> Path:
        part = PurePosixPath(relative)
        if not relative or part.is_absolute() or ".." in part.parts or "\\" in relative:
            raise ImportPathError("Journal path is not a confined relative path")
        candidate = root.joinpath(*part.parts)
        resolved = assert_within(candidate, root)
        for parent in (candidate, *candidate.parents):
            if parent == root:
                break
            if parent.is_symlink():
                raise ImportPathError("Import paths may not traverse symbolic links")
        return resolved

    @staticmethod
    def _identity(path: Path) -> ImportFileIdentity | None:
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError("Import artifact is not a regular file")
        return ImportFileIdentity.from_stat(metadata)

    @classmethod
    def _verify(cls, path: Path, identity: ImportFileIdentity | None, digest: str | None) -> None:
        if identity is None or cls._identity(path) != identity or digest is None or sha256_of(path) != digest:
            raise OSError("Import artifact changed or ownership is unknown")

    def verify_source(self) -> None:
        self._revalidate()
        self._verify(self.source, self.source_identity, self.operation.source_sha256)

    def verify_target(self, row: MediaImport, title: Title, episode: Episode | None) -> None:
        self._revalidate()
        source = assert_within(Path(row.source_path), self.staging)
        plan = plan_destination(self.media, title, episode, source.suffix)
        if source != self.source or plan.relative_path.as_posix() != self.operation.destination_path:
            raise OSError("Import source or identification target changed before commit")

    def _revalidate(self) -> None:
        if (
            self.settings.import_staging_dir is None
            or self.settings.media_root is None
            or self.settings.import_staging_dir.resolve() != self.staging
            or self.settings.media_root.resolve() != self.media
        ):
            raise ImportPathError("Import roots changed during the operation")
        self._path(self.operation.source_path, self.staging)
        self._path(self.operation.destination_path, self.media)
        self._path(self.operation.temp_path, self.media)
        if self.operation.superseded_path is not None:
            self._path(self.operation.superseded_path, self.media)

    @staticmethod
    def _sync_directory(path: Path) -> None:
        # Windows' Python file API cannot open directories; native renames still provide process-crash atomicity.
        if sys.platform != "win32":
            descriptor = os.open(path, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    @classmethod
    def _mkdir(cls, path: Path, root: Path) -> None:
        missing: list[Path] = []
        current = path
        while not current.exists():
            missing.append(current)
            current = current.parent
        for directory in reversed(missing):
            cls._path(directory.relative_to(root).as_posix(), root)
            directory.mkdir(exist_ok=True)
            cls._sync_directory(directory.parent)

    def create_temp(self) -> ImportFileIdentity:
        self.verify_source()
        self._mkdir(self.temp.parent, self.media)
        self._path(self.operation.temp_path, self.media)
        with self.temp.open("xb") as handle:
            handle.flush()
            os.fsync(handle.fileno())
            identity = ImportFileIdentity.from_stat(os.fstat(handle.fileno()))
        self._sync_directory(self.temp.parent)
        return identity

    def copy_temp(self) -> ImportFileIdentity:
        self.verify_source()
        current = self._identity(self.temp)
        if self.temp_identity is None or current is None or not self.temp_identity.same_file(current):
            raise OSError("Temporary file ownership is unknown")
        with self.source.open("rb") as source, self.temp.open("r+b") as destination:
            if ImportFileIdentity.from_stat(os.fstat(source.fileno())) != self.source_identity:
                raise OSError("Source changed before copy")
            if not self.temp_identity.same_file(ImportFileIdentity.from_stat(os.fstat(destination.fileno()))):
                raise OSError("Temporary file changed before copy")
            destination.truncate()
            shutil.copyfileobj(source, destination, IMPORT_COPY_CHUNK_BYTES)
            destination.flush()
            os.fsync(destination.fileno())
            copied = ImportFileIdentity.from_stat(os.fstat(destination.fileno()))
        self.verify_source()
        if copied != self._identity(self.temp):
            raise OSError("Temporary file replaced during copy")
        return copied

    def install(self) -> None:
        self.verify_source()
        if self._identity(self.temp) is None:
            self.verify_installed()
            return
        self._verify(self.temp, self.temp_identity, self.operation.source_sha256)
        current = self._identity(self.destination)
        if self.archive is not None:
            if self._identity(self.archive) is None:
                self._verify(self.destination, self.previous_identity, self.operation.destination_sha256)
                self._mkdir(self.archive.parent, self.media)
                self._revalidate()
                rename_exclusive(self.destination, self.archive)
                self._sync_directory(self.archive.parent)
                self._sync_directory(self.destination.parent)
                current = None
            else:
                self._verify(self.archive, self.previous_identity, self.operation.destination_sha256)
        if current is not None:
            raise OSError("Destination unexpectedly exists; no file was overwritten")
        self._revalidate()
        rename_exclusive(self.temp, self.destination)
        self._sync_directory(self.destination.parent)

    def verify_installed(self) -> str:
        self._revalidate()
        self._verify(self.destination, self.temp_identity, self.operation.source_sha256)
        if self.archive is not None:
            self._verify(self.archive, self.previous_identity, self.operation.destination_sha256)
        return self.operation.source_sha256

    def duplicate_at_destination(self) -> bool:
        if self.operation.destination_sha256 != self.operation.source_sha256:
            return False
        self.verify_source()
        self._verify(self.destination, self.previous_identity, self.operation.destination_sha256)
        return True

    def rollback(self) -> None:
        """Compensate only when source and every affected artifact still have provable ownership."""
        self.verify_source()
        current, temp = self._identity(self.destination), self._identity(self.temp)
        archived = None if self.archive is None else self._identity(self.archive)
        if self.previous_identity is not None:
            if archived is not None:
                self._verify(self.archive, self.previous_identity, self.operation.destination_sha256)
            elif current != self.previous_identity:
                raise OSError("Original destination cannot be located for rollback")
            else:
                self._verify(self.destination, self.previous_identity, self.operation.destination_sha256)
        if current is not None and current != self.previous_identity:
            self._verify(self.destination, self.temp_identity, self.operation.source_sha256)
        if temp is not None and (self.temp_identity is None or not self.temp_identity.same_file(temp)):
            raise OSError("Unknown temporary artifact blocks rollback")
        if temp is not None and self.temp_identity is not None and self.temp_identity.size_bytes:
            self._verify(self.temp, self.temp_identity, self.operation.source_sha256)
        if current is not None and current != self.previous_identity:
            self._revalidate()
            self.destination.unlink()
            self._sync_directory(self.destination.parent)
            current = None
        if archived is not None:
            if current is not None:
                raise OSError("Destination occupied; original archive retained")
            self._revalidate()
            rename_exclusive(self.archive, self.destination)
            self._sync_directory(self.destination.parent)
            self._sync_directory(self.archive.parent)
        if temp is not None:
            self._revalidate()
            self.temp.unlink()
            self._sync_directory(self.temp.parent)

    def cleanup_source(self) -> None:
        self.verify_installed()
        if self._identity(self.source) is not None:
            self.verify_source()
            self._revalidate()
            self.source.unlink()
            self._sync_directory(self.source.parent)
