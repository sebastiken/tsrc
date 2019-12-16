from typing import cast, Optional, List, Tuple  # noqa
from path import Path
import cli_ui as ui

import tsrc
import tsrc.manifest
from .manifest_config import ManifestConfig


class LocalManifest:
    """ Represent a manifest that has been cloned locally inside the
    hidden <workspace>/.tsrc directory, along with its configuration

    """

    def __init__(self, workspace_path: Path) -> None:
        hidden_path = workspace_path / ".tsrc"
        self.clone_path = hidden_path / "manifest"
        self.cfg_path = hidden_path / "manifest.yml"
        self.manifest = None  # type: Optional[tsrc.manifest.Manifest]

    @property
    def branch(self) -> str:
        return self.load_config().branch

    @property
    def shallow(self) -> bool:
        return self.load_config().shallow

    @property
    def copyfiles(self) -> List[Tuple[str, str]]:
        assert self.manifest, "manifest is empty. Did you call load()?"
        return self.manifest.copyfiles

    @property
    def active_groups(self) -> List[str]:
        return self.load_config().groups

    def get_repos(self) -> List[tsrc.Repo]:
        assert self.manifest, "manifest is empty. Did you call load()?"
        return self.manifest.get_repos(groups=self.active_groups)

    def create_snapshot(self, yml_path: Path, force: bool, sha1: bool) -> None:
        config = self.load_config()
        if not yml_path:
            if not config.file_path:
                yml_path = self.clone_path / "manifest.yml"
            else:
                yml_path = config.file_path

        if yml_path.exists() and not force:
            message = "Manifest already found in {}. Use -f to force creation."
            raise tsrc.Error(message.format(yml_path))
        self.manifest = tsrc.manifest.create_snapshot(yml_path, sha1)

    def load(self) -> None:
        config = self.load_config()
        if not config.file_path:
            yml_path = self.clone_path / "manifest.yml"
        else:
            yml_path = config.file_path
        if not yml_path.exists():
            message = "No manifest found in {}. Did you run `tsrc init` ?"
            raise tsrc.Error(message.format(yml_path))
        self.manifest = tsrc.manifest.load(yml_path)

    def get_gitlab_url(self) -> Optional[str]:
        assert self.manifest, "manifest is empty. Did you call load()?"
        gitlab_config = self.manifest.gitlab
        if not gitlab_config:
            return None
        return cast(Optional[str], gitlab_config.get("url", None))

    def get_github_enterprise_url(self) -> Optional[str]:
        assert self.manifest, "manifest is empty. Did you call load()?"
        github_enterprise_config = self.manifest.github_enterprise
        if not github_enterprise_config:
            return None
        return cast(Optional[str], github_enterprise_config.get("url", None))

    def configure(self, manifest_config: ManifestConfig) -> None:
        if not manifest_config.url and not manifest_config.file_path:
            raise tsrc.Error("Manifest URL is required")
        if manifest_config.url:
            self._ensure_git_state(manifest_config)
        self.save_config(manifest_config)

    def update(self) -> None:
        config = self.load_config()
        if config.file_path:
            return

        ui.info_2("Updating manifest")
        if not self.clone_path.exists():
            message = "Could not find manifest in {}. "
            message += "Did you run `tsrc init` ?"
            raise tsrc.Error(message.format(self.clone_path))
        cmd = ("fetch", "--prune", "origin")
        tsrc.git.run(self.clone_path, *cmd)
        cmd = ("reset", "--hard", "@{upstream}")
        tsrc.git.run(self.clone_path, *cmd)

    def save_config(self, config: ManifestConfig) -> None:
        config.save_to_file(self.cfg_path)

    def load_config(self) -> ManifestConfig:
        return ManifestConfig.from_file(self.cfg_path)

    def _ensure_git_state(self, config: ManifestConfig) -> None:
        if self.clone_path.exists():
            self._reset_manifest_clone(config)
        else:
            self._clone_manifest(config)

    def _reset_manifest_clone(self, config: ManifestConfig) -> None:
        tsrc.git.run(self.clone_path, "remote", "set-url", "origin", config.url)

        tsrc.git.run(self.clone_path, "fetch")
        tsrc.git.run(self.clone_path, "checkout", "-B", config.branch)
        # fmt: off
        tsrc.git.run(
            self.clone_path, "branch", config.branch,
            "--set-upstream-to", "origin/%s" % config.branch
        )
        # fmt: on
        if config.tag:
            ref = config.tag
        else:
            ref = "origin/%s" % config.branch
        tsrc.git.run(self.clone_path, "reset", "--hard", ref)

    def _clone_manifest(self, config: ManifestConfig) -> None:
        parent, name = self.clone_path.splitpath()
        parent.makedirs_p()
        ref = ""  # type: str
        if config.tag:
            ref = config.tag
        elif config.branch:
            ref = config.branch
        args = ["clone", config.url, name]
        if ref:
            args += ["--branch", ref]
        tsrc.git.run(self.clone_path.parent, *args)
