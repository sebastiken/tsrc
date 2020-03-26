""" Entry point for tsrc snapshot """

import argparse
import cli_ui as ui

import tsrc.cli


def main(args: argparse.Namespace) -> None:
    workspace = tsrc.cli.get_workspace(args)
    ui.info_1("Creating snapshot on %s" % args.file_path)
    workspace.create_snapshot(
        force=args.force,
        file_path=args.file_path,
        sha1=args.sha1,
        define_groups=args.define_groups)
