""" Entry point for tsrc reset """

from typing import List, Union

import argparse
import collections
import shutil

import cli_ui as ui
from path import Path

import tsrc.cli


ResetOrError = Union[str, Exception]
#CollectedStatuses = Dict[str, StatusOrError]


def describe_reset(reset: ResetOrError) -> List[ui.Token]:
    """ Returns a list of tokens suitable for ui.info() """
    if isinstance(reset, tsrc.errors.MissingRepo):
        return [ui.red, "error: missing repo"]
    if isinstance(reset, Exception):
        return [ui.red, "error: ", reset]
    return [ui.green, reset]


def erase_last_line() -> None:
    terminal_size = shutil.get_terminal_size()
    ui.info(" " * terminal_size.columns, end="\r")


class ResetCollector(tsrc.Task[tsrc.Repo]):
    def __init__(self, workspace_path: Path, snapshot_file: Path) -> None:
        self.workspace_path = workspace_path
        self.snapshot_file = snapshot_file
        self.reseted_repos = collections.OrderedDict()  # type: CollectedStatuses
        self.num_repos = 0

    def display_item(self, repo: tsrc.Repo) -> str:
        return repo.src

    def process(self, index: int, total: int, repo: tsrc.Repo) -> None:
        ui.info_count(index, total, repo.src, end="\r")
        full_path = self.workspace_path / repo.src

        # Clone repo
        if not full_path.exists():
            self.reseted_repos[repo.src] = tsrc.errors.MissingRepo(repo.src)
            return

        try:
            self.reseted_repos[repo.src] = tsrc.git.reset_repo(
                full_path, repo.branch, repo.sha1)
        except Exception as e:
            self.reseted_repos[repo.src] = e
        erase_last_line()

    def on_start(self, num_items: int) -> None:
        ui.info_1("Resetting %d repos" % num_items)
        self.num_repos = num_items

    def on_success(self) -> None:
        erase_last_line()
        if not self.reseted_repos:
            ui.info_2("Workspace is empty")
            return
        ui.info_2("Workspace status:")
        max_src = max(len(x) for x in self.reseted_repos.keys())
        for src, reset in self.reseted_repos.items():
            message = [ui.green, "*", ui.reset, src.ljust(max_src)]
            message += describe_reset(reset)
            ui.info(*message)


def main(args: argparse.Namespace) -> None:
    ui.info_1("Resetting to snapshot %s" % args.file_path)

    workspace = tsrc.cli.get_workspace(args)
    workspace.load_manifest()

    snapshot_manifest = tsrc.manifest.load(args.file_path)
    snapshot_manifest.clone_missing(workspace.root_path, workspace.shallow)
    snapshot_repos = snapshot_manifest.get_repos()
    reset_collector = ResetCollector(workspace.root_path, args.file_path)

    tsrc.run_sequence(snapshot_repos, reset_collector)
