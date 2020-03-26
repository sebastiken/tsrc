""" Entry point for tsrc status """

from typing import Dict, List, Union

import argparse
import collections
import shutil

import cli_ui as ui
from path import Path

import tsrc
import tsrc.errors
import tsrc.cli
import tsrc.git


StatusOrError = Union[tsrc.git.Status, Exception]
CollectedStatuses = Dict[str, StatusOrError]


def describe_status(status: StatusOrError, show_sha1: bool) -> List[ui.Token]:
    """ Returns a list of tokens suitable for ui.info() """
    if isinstance(status, tsrc.errors.MissingRepo):
        return [ui.red, "error: missing repo"]
    if isinstance(status, Exception):
        return [ui.red, "error: ", status]
    return describe_git_status(status, show_sha1)


def describe_git_status(
    git_status: tsrc.git.Status, show_sha1: bool
) -> List[ui.Token]:
    res = []  # type: List[ui.Token]
    res += describe_branch(git_status, show_sha1)
    res += describe_position(git_status)
    res += describe_dirty(git_status)
    res += describe_stash(git_status)
    return res


def describe_stash(git_status: tsrc.git.Status) -> List[ui.Token]:
    res = list()  # type: List[ui.Token]
    if git_status.stashed_entries:
        res += [ui.yellow, git_status.stashed_entries, "stashed entries"]
    return res


def describe_branch(
    git_status: tsrc.git.Status, show_sha1: bool
) -> List[ui.Token]:
    res = list()  # type: List[ui.Token]
    if git_status.branch:
        res += [ui.green, git_status.branch]
    if show_sha1 and git_status.sha1:
        res += [ui.red, git_status.sha1]
    if git_status.tag:
        res += [ui.reset, ui.brown, "on", git_status.tag]
    return res


def commit_string(number: int) -> str:
    if number == 1:
        return "commit"
    else:
        return "commits"


def describe_position(git_status: tsrc.git.Status) -> List[ui.Token]:
    res = []  # type: List[ui.Token]
    if git_status.ahead != 0:
        up = ui.Symbol("↑", "+")
        n_commits = commit_string(git_status.ahead)
        ahead_desc = "{}{} {}".format(up.as_string, git_status.ahead, n_commits)
        res += [ui.blue, ahead_desc, ui.reset]
    if git_status.behind != 0:
        down = ui.Symbol("↓", "-")
        n_commits = commit_string(git_status.behind)
        behind_desc = "{}{} {}".format(down.as_string, git_status.behind, n_commits)
        res += [ui.blue, behind_desc, ui.reset]
    return res


def describe_dirty(git_status: tsrc.git.Status) -> List[ui.Token]:
    res = []  # type: List[ui.Token]
    if git_status.dirty:
        res += [ui.red, "(dirty)"]
    return res


def erase_last_line() -> None:
    terminal_size = shutil.get_terminal_size()
    ui.info(" " * terminal_size.columns, end="\r")


class StatusCollector(tsrc.Task[tsrc.Repo]):
    def __init__(self, workspace_path: Path, args: argparse.Namespace) -> None:
        self.workspace_path = workspace_path
        self.statuses = collections.OrderedDict()  # type: CollectedStatuses
        self.num_repos = 0
        self.show_sha1 = args.show_sha1

    def display_item(self, repo: tsrc.Repo) -> str:
        return repo.src

    def process(self, index: int, total: int, repo: tsrc.Repo) -> None:
        ui.info_count(index, total, repo.src, end="\r")
        full_path = self.workspace_path / repo.src

        if not full_path.exists():
            self.statuses[repo.src] = tsrc.errors.MissingRepo(repo.src)
            return

        try:
            self.statuses[repo.src] = tsrc.git.get_status(full_path)
        except Exception as e:
            self.statuses[repo.src] = e
        erase_last_line()

    def on_start(self, num_items: int) -> None:
        ui.info_1("Collecting statuses of %d repos" % num_items)
        self.num_repos = num_items

    def on_success(self) -> None:
        erase_last_line()
        if not self.statuses:
            ui.info_2("Workspace is empty")
            return
        ui.info_2("Workspace status:")
        max_src = max(len(x) for x in self.statuses.keys())
        for src, status in self.statuses.items():
            message = [ui.green, "*", ui.reset, src.ljust(max_src)]
            message += describe_status(status, self.show_sha1)
            ui.info(*message)


def main(args: argparse.Namespace) -> None:
    workspace = tsrc.cli.get_workspace(args)
    status_collector = StatusCollector(workspace.root_path, args)
    workspace.load_manifest()
    tsrc.run_sequence(workspace.get_repos(), status_collector)
