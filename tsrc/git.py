""" git tools """


import os
import subprocess
from typing import Any, Dict, Iterable, Tuple, Optional  # noqa

from path import Path
import cli_ui as ui

import tsrc


class Error(tsrc.Error):
    pass


class CommandError(Error):
    def __init__(
        self, working_path: Path, cmd: Iterable[str], *, output: Optional[str] = None
    ) -> None:
        self.cmd = cmd
        self.working_path = working_path
        self.output = output
        message = "`git {cmd}` from {working_path} failed"
        message = message.format(cmd=" ".join(cmd), working_path=working_path)
        if output:
            message += "\n" + output
        super().__init__(message)


class NoSuchWorkingPath(Error):
    def __init__(self, path: Path) -> None:
        super().__init__("'{}' does not exist".format(path))


class WorktreeNotFound(Error):
    def __init__(self, working_path: Path) -> None:
        super().__init__("'{}' is not inside a git repository".format(working_path))


class NoTrackingRef(Error):
    def __init__(self, working_path: Path) -> None:
        super().__init__("'{}' has not tracking ref".format(working_path))


def assert_working_path(path: Path) -> None:
    if not path.exists():
        raise NoSuchWorkingPath(path)


class Status:
    def __init__(self, working_path: Path) -> None:
        self.working_path = working_path
        self.untracked = 0
        self.staged = 0
        self.not_staged = 0
        self.added = 0
        self.ahead = 0
        self.behind = 0
        self.dirty = False
        self.tag = None  # type: Optional[str]
        self.branch = None  # type: Optional[str]
        self.sha1 = None  # type: Optional[str]
        self.stashed_entries = None  # type: Optional[str]

    def update(self) -> None:
        self.update_sha1()
        self.update_branch()
        self.update_tag()
        self.update_remote_status()
        self.update_worktree_status()

    def update_sha1(self) -> None:
        self.sha1 = get_sha1(self.working_path, short=True)

    def update_branch(self) -> None:
        try:
            self.branch = get_current_branch(self.working_path)
        except Error:
            pass

    def update_tag(self) -> None:
        try:
            self.tag = get_current_tag(self.working_path)
        except Error:
            pass

    def update_remote_status(self) -> None:
        rc, ahead_rev = run_captured(
            self.working_path, "rev-list", "@{upstream}..HEAD", check=False
        )
        if rc == 0:
            self.ahead = len(ahead_rev.splitlines())

        rc, behind_rev = run_captured(
            self.working_path, "rev-list", "HEAD..@{upstream}", check=False
        )
        if rc == 0:
            self.behind = len(behind_rev.splitlines())

    def update_worktree_status(self) -> None:
        _, out = run_captured(self.working_path, "status", "--porcelain")

        for line in out.splitlines():
            if line.startswith("??"):
                self.untracked += 1
                self.dirty = True
            if line.startswith(" M"):
                self.staged += 1
                self.dirty = True
            if line.startswith(" .M"):
                self.not_staged += 1
                self.dirty = True
            if line.startswith("A "):
                self.added += 1
                self.dirty = True

        _, out = run_captured(self.working_path, "stash", "list")
        self.stashed_entries = len(out.splitlines())

def run(working_path: Path, *cmd: str, check: bool = True) -> None:
    """ Run git `cmd` in given `working_path`

    Raise GitCommandError if return code is non-zero and `check` is True.
    """
    assert_working_path(working_path)
    git_cmd = list(cmd)
    git_cmd.insert(0, "git")

    ui.debug(ui.lightgray, working_path, "$", ui.reset, *git_cmd)
    returncode = subprocess.call(git_cmd, cwd=working_path)
    if returncode != 0 and check:
        raise CommandError(working_path, cmd)


def run_captured(working_path: Path, *cmd: str, check: bool = True) -> Tuple[int, str]:
    """ Run git `cmd` in given `working_path`, capturing the output

    Return a tuple (returncode, output).

    Raise GitCommandError if return code is non-zero and check is True
    """
    assert_working_path(working_path)
    git_cmd = list(cmd)
    git_cmd.insert(0, "git")
    options = dict()  # type: Dict[str, Any]
    options["stdout"] = subprocess.PIPE
    options["stderr"] = subprocess.STDOUT

    ui.debug(ui.lightgray, working_path, "$", ui.reset, *git_cmd)
    process = subprocess.Popen(git_cmd, cwd=working_path, **options)
    out, _ = process.communicate()
    out = out.decode("utf-8")
    if out.endswith("\n"):
        out = out.strip("\n")
    returncode = process.returncode
    ui.debug(ui.lightgray, "[%i]" % returncode, ui.reset, out)
    if check and returncode != 0:
        raise CommandError(working_path, cmd, output=out)
    return returncode, out


def get_sha1(working_path: Path, short: bool = False, ref: str = "HEAD") -> str:
    cmd = ["rev-parse"]
    if short:
        cmd.append("--short")
    cmd.append(ref)
    _, output = run_captured(working_path, *cmd)
    return output


def get_current_branch(working_path: Path) -> str:
    cmd = ("rev-parse", "--abbrev-ref", "HEAD")
    _, output = run_captured(working_path, *cmd)
    if output == "HEAD":
        raise Error("Not an any branch")
    return output


def get_current_tag(working_path: Path) -> str:
    cmd = ("tag", "--points-at", "HEAD")
    _, output = run_captured(working_path, *cmd)
    return output


def get_repo_root(working_path: Optional[Path] = None) -> Path:
    if not working_path:
        working_path = Path(os.getcwd())
    cmd = ("rev-parse", "--show-toplevel")
    status, output = run_captured(working_path, *cmd, check=False)
    if status != 0:
        raise WorktreeNotFound(working_path)
    return Path(output)


def find_ref(repo: Path, candidate_refs: Iterable[str]) -> str:
    """ Find the first reference that exists in the given repo """
    run(repo, "fetch", "--all", "--prune")
    for candidate_ref in candidate_refs:
        code, _ = run_captured(repo, "rev-parse", candidate_ref, check=False)
        if code == 0:
            return candidate_ref
    ref_list = ", ".join(candidate_refs)
    raise Error("Could not find any of:", ref_list, "in repo", repo)


def reset(repo: Path, ref: str) -> None:
    ui.info_2("Resetting", repo, "to", ref)
    run(repo, "reset", "--hard", ref)


def get_status(working_path: Path) -> Status:
    status = Status(working_path)
    status.update()
    return status


def reset_repo(repo: Path, branch: str, sha1: str) -> str:
    ui.info_2("Fetching all for", repo)
    run(repo, "fetch", "--all", "--prune")

    # Get actual branch
    current_branch = get_current_branch(repo)

    if branch != current_branch:
        run(repo, "checkout", branch)

    tracking_ref = get_tracking_ref(repo)
    if not tracking_ref:
        # Try to get tracking ref using origin
        # and branch name
        ui.info_2(ui.red, "No tracking ref for", ui.reset, ui.blue, repo.name)
        ui.info_2(ui.brown, "Trying to guess it from origin and local branch name for", branch)

        candidates = guess_tracking_ref(repo, sha1)
        # TODO: What to do when multiple remotes
        for candidate in candidates:
            remote, remote_branch = candidate.split('/')
            if branch == remote_branch:
                tracking_ref = candidate
                break

        if not tracking_ref:
            raise NoTrackingRef(repo)

        ui.info_2(ui.green, "Guessed remote tracking branch", ui.blue,  branch)

    run_captured(repo, "merge", "--ff-only", tracking_ref)
    reset(repo, sha1)
    return "Reseted to {}".format(sha1)


def guess_tracking_ref(working_path: Path, sha1: str) -> Optional[str]:
    rc, out = run_captured(
        working_path,
        "branch", "-r",
        "--contains", sha1,
        check=False
    )

    if rc == 0:
        candidates = [c.strip() for c in out.splitlines()]
        return candidates
    else:
        return None


def get_tracking_ref(working_path: Path) -> Optional[str]:
    # fmt: off
    rc, out = run_captured(
        working_path,
        "rev-parse", "--abbrev-ref",
        "--symbolic-full-name", "@{upstream}",
        check=False
    )
    # fmt: on
    if rc == 0:
        return out
    else:
        return None


def is_shallow(working_path: Path) -> bool:
    root = get_repo_root(working_path)
    res = (root / ".git/shallow").exists()  # type: bool
    return res
