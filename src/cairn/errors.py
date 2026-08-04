class CairnError(Exception):
    """A condition Cairn can describe to the user, reported without a traceback."""


class GitUnavailableError(CairnError):
    """git could not be executed at all."""


class GitCommandError(CairnError):
    """A git invocation Cairn depends on exited non-zero."""

    def __init__(self, args: list[str], returncode: int, stderr: str):
        self.args_run = args
        self.returncode = returncode
        self.stderr = (stderr or "").strip()
        detail = f": {self.stderr}" if self.stderr else ""
        super().__init__(f"git {' '.join(args)} failed (exit {returncode}){detail}")
