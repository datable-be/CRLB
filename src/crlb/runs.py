"""Run bookkeeping shared by all steps: timestamps and the git commit of the code."""

import subprocess
from datetime import UTC, datetime


def utc_now() -> str:
    """Return the current time as an ISO 8601 string in UTC, to the second."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def git_commit() -> str | None:
    """Return the current git commit, with '-dirty' if the tree has changes; None outside git."""
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
        ).stdout
    except OSError, subprocess.CalledProcessError:
        return None
    return f"{commit}-dirty" if status.strip() else commit
