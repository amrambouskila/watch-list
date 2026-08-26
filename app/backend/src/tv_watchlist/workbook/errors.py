"""Failure modes specific to editing live Excel workbooks."""

from __future__ import annotations


class WorkbookError(Exception):
    """Base class for workbook access failures."""


class CategoryNotFoundError(WorkbookError):
    """No workbook in the library matches the requested category id."""


class WorkbookLockedError(WorkbookError):
    """The workbook is open in Excel, so it cannot be written."""


class StaleWorkbookError(WorkbookError):
    """The file changed on disk since the client last read it."""


class MissingWatchColumnError(WorkbookError):
    """The sheet has no Watched? column to write to."""


class UnknownColumnError(WorkbookError):
    """A write referenced a column key that this sheet does not have."""


class InvalidChoiceError(WorkbookError):
    """A write supplied a value the sheet's own dropdown would reject."""


class DuplicateCategoryError(WorkbookError):
    """A workbook with the requested name already exists."""


class RowNotFoundError(WorkbookError):
    """The requested row number is outside the sheet's data range."""


class UnreadableWorkbookError(WorkbookError):
    """The file exists but cannot be opened as a workbook."""


class InvalidNameError(WorkbookError):
    """The requested filename is not one this filesystem will accept."""
