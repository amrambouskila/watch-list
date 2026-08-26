"""Failure modes specific to running the research agent."""

from __future__ import annotations


class AgentError(Exception):
    """Base class for research-agent failures."""


class BlockedUrlError(AgentError):
    """The requested URL is not a public http(s) endpoint the agent may reach."""


class FetchFailedError(AgentError):
    """Neither the cheap path nor the browser could read the page."""


class UnknownSessionError(AgentError):
    """No live chat session has the requested id."""


class UnknownProposalError(AgentError):
    """No live session is holding a proposal with the requested id."""


class HeroDownloadError(AgentError):
    """The candidate image could not be downloaded, or was larger than a card image may be."""


class UnsupportedImageError(AgentError):
    """The downloaded bytes are not one of the raster formats a hero image may be."""


class UnsafeHeroPathError(AgentError):
    """The resolved hero filename would land outside the heroes folder."""


class HeroChoiceRequiredError(AgentError):
    """A hero proposal was approved, but artwork is chosen by eye rather than written from a diff."""


class NoHeroCandidatesError(AgentError):
    """A candidate was chosen on a proposal that offers a change to approve, not artwork."""


class UnknownHeroCandidateError(AgentError):
    """The chosen candidate is not one this proposal offered."""
