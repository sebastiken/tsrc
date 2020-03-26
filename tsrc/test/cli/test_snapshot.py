from path import Path
import pytest

import tsrc.cli

from cli_ui.tests import MessageRecorder
from tsrc.test.helpers.cli import CLI
from tsrc.test.helpers.git_server import GitServer
from tsrc.errors import Error


def test_create_snapshot(
    tsrc_cli: CLI,
    git_server: GitServer,
    workspace_path: Path,
    message_recorder: MessageRecorder,
) -> None:
    git_server.add_repo("foo/bar")
    git_server.add_repo("spam/eggs")
    git_server.push_file("foo/bar", "CMakeLists.txt")
    git_server.push_file("spam/eggs", "CMakeLists.txt")
    manifest_url = git_server.manifest_url
    manifest_path = workspace_path + '/manifest.yml'
    tsrc_cli.run("init", manifest_url)
    tsrc_cli.run("snapshot", "-c")

    with open(manifest_path, 'r') as f:
        unexistent = filter(lambda x: x.find('fish') != -1, f.readlines())
        assert len(list(unexistent)) == 0

    tsrc.git.run(workspace_path / "spam/eggs", "checkout", "-b", "fish")

    with pytest.raises(Error, match=r"^Manifest already found .*"):
        tsrc_cli.run("snapshot", "-c")

    tsrc_cli.run("snapshot", "-c", "-f")

    with open(manifest_path, 'r') as f:
        unexistent = filter(lambda x: x.find('fish') != -1, f.readlines())
        assert len(list(unexistent)) == 1

    assert message_recorder.find("Creating snapshot")
    assert manifest_path.exists()

    with open(manifest_path, 'r') as f:
        print(f.readlines())
