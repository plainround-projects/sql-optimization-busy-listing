"""Named errors of the listing. Each says what the caller got wrong, in the caller's terms."""


class LabError(Exception):
    """Base class of every error this package raises on purpose."""


class InvalidCursorError(LabError):
    """A keyset cursor that this service did not issue, or that was damaged on the way."""


class UnknownStrategyError(LabError):
    """A listing strategy other than naive, batched or keyset."""


class PageNumberNotSupportedError(LabError):
    """Keyset paging has no page numbers: the client passes the cursor from the previous page."""


class InvalidPageError(LabError):
    """A negative page number."""


class LessonInterruptedError(LabError):
    """The replay was asked to stop (SIGINT or SIGTERM) between two phases."""


class PlanParseError(LabError):
    """A query plan did not have the lines or fields the lesson reads."""
