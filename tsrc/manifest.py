""" manifests for tsrc """

import operator
import os
from typing import cast, Any, Dict, List, NewType, Optional, Tuple  # noqa

from path import Path
import schema
import cli_ui as ui

import tsrc

ManifestConfig = NewType("ManifestConfig", Dict[str, Any])
RepoConfig = NewType("RepoConfig", Dict[str, Any])

GitLabConfig = NewType("GitLabConfig", Dict[str, Any])
GithubEnterpriseConfig = NewType("GithubEnterpriseConfig", Dict[str, Any])


class RepoNotFound(tsrc.Error):
    def __init__(self, src: str) -> None:
        super().__init__("No repo found in '%s'" % src)


class Manifest:
    def __init__(self) -> None:
        self._repos = list()  # type: List[tsrc.Repo]
        self.copyfiles = list()  # type: List[Tuple[str, str]]
        self.gitlab = None  # type: Optional[GitLabConfig]
        self.github_enterprise = None  # type: Optional[GithubEnterpriseConfig]
        self.group_list = None  # type:  Optional[tsrc.GroupList[str]]

    def load(self, config: ManifestConfig) -> None:
        self.copyfiles = list()
        self.gitlab = config.get("gitlab")
        self.github_enterprise = config.get("github_enterprise")
        repos = config.get("repos") or list()
        for repo_config in repos:
            self._handle_repo(repo_config)
            self._handle_copies(repo_config)

        self._handle_groups(config)

    def _handle_repo(self, repo_config: RepoConfig) -> None:
        src = repo_config["src"]
        branch = repo_config.get("branch", "master")
        tag = repo_config.get("tag")
        sha1 = repo_config.get("sha1")
        url = repo_config.get("url")
        if url:
            origin = tsrc.Remote(name="origin", url=url)
            remotes = [origin]
        else:
            remotes = self._handle_remotes(repo_config)
        repo = tsrc.Repo(src=src, branch=branch, sha1=sha1, tag=tag, remotes=remotes)
        self._repos.append(repo)

    def _handle_remotes(self, repo_config: RepoConfig) -> List[tsrc.Remote]:
        remotes_config = repo_config.get("remotes")
        res = list()  # type: List[tsrc.Remote]
        if remotes_config:
            for remote_config in remotes_config:
                remote = tsrc.Remote(
                    name=remote_config["name"], url=remote_config["url"]
                )
                res.append(remote)
        return res

    def _handle_copies(self, repo_config: RepoConfig) -> None:
        if "copy" not in repo_config:
            return
        to_cp = repo_config["copy"]
        for item in to_cp:
            src_copy = item["src"]
            dest_copy = item.get("dest", src_copy)
            src_copy = os.path.join(repo_config["src"], src_copy)
            self.copyfiles.append((src_copy, dest_copy))

    def _handle_groups(self, config: ManifestConfig) -> None:
        elements = set(repo.src for repo in self._repos)
        self.group_list = tsrc.GroupList(elements=elements)
        groups_config = config.get("groups", dict())
        for name, group_config in groups_config.items():
            elements = group_config["repos"]
            includes = group_config.get("includes", list())
            self.group_list.add(name, elements, includes=includes)

    def get_repos(
        self, groups: Optional[List[str]] = None, all_: bool = False
    ) -> List[tsrc.Repo]:
        if all_:
            return self._repos

        if not groups:
            if self._has_default_group():
                return self._get_repos_in_groups(["default"])
            else:
                return self._repos

        return self._get_repos_in_groups(groups)

    def _has_default_group(self) -> bool:
        assert self.group_list
        return self.group_list.get_group("default") is not None

    def _get_repos_in_groups(self, groups: List[str]) -> List[tsrc.Repo]:
        assert self.group_list
        elements = self.group_list.get_elements(groups=groups)
        res = list()
        for src in elements:
            res.append(self.get_repo(src))
        return sorted(res, key=operator.attrgetter("src"))

    def get_repo(self, src: str) -> tsrc.Repo:
        for repo in self._repos:
            if repo.src == src:
                return repo
        raise RepoNotFound(src)


def validate_repo(data: Any) -> None:
    copy_schema = {"src": str, schema.Optional("dest"): str}
    remote_schema = {"name": str, "url": str}
    repo_schema = schema.Schema(
        {
            "src": str,
            schema.Optional("branch"): str,
            schema.Optional("copy"): [copy_schema],
            schema.Optional("sha1"): str,
            schema.Optional("tag"): str,
            schema.Optional("remotes"): [remote_schema],
            schema.Optional("url"): str,
        }
    )
    repo_schema.validate(data)
    url = data.get("url")
    remotes = data.get("remotes")
    if url and remotes:
        raise schema.SchemaError(
            "Repo config cannot contain both an url and a list of remotes"
        )
    if not url and not remotes:
        raise schema.SchemaError(
            "Repo config should contain either a url or a non-empty list of remotes"
        )


def create_snapshot(manifest_path: Path, sha1: bool = False) -> Manifest:
    # TODO: traverse current directory, but it would be a parameter
    from_dir = Path('.')

    repos = []
    for git_dir in from_dir.walk('.git'):
        name = str(git_dir.relpath().parent)
        repo = {'src': name}

        # Get currentbranch
        cmd = ["rev-parse", "--abbrev-ref", "HEAD"]
        _, out = tsrc.git.run_captured(git_dir, *cmd)
        repo['branch'] = out

        # Get current commit
        if sha1:
            try:
                cmd = ["rev-parse", "--short", "--verify", "HEAD"]
                _, out = tsrc.git.run_captured(git_dir, *cmd)
                repo['sha1'] = out
            except tsrc.git.CommandError as e:
                message = "Repo {} has no commits. Discarded."
                ui.warning(message.format(name))
                continue

        # Get all remotes
        cmd = ["remote"]
        _, out = tsrc.git.run_captured(git_dir, *cmd)
        remotes = filter(lambda r: r, out.split('\n'))

        remotes_dict = {}
        for remote in remotes:
            cmd = ["remote", "get-url", remote]
            _, url = tsrc.git.run_captured(git_dir, *cmd)
            remotes_dict.setdefault(remote, url)

        # Get url of remotes
        if not remotes_dict:
            message = "Repo {} has no remotes. Discarded."
            ui.warning(message.format(name))
            continue
        elif len(remotes_dict) == 1:
            repo['url'] = list(remotes_dict.values())[0]
        else:
            repo['remotes'] = [{
                'name': k, 'url': remotes_dict[k]} for k in remotes_dict.keys()]

        repos.append(repo)

    tsrc.config.dump_config({'repos': repos}, manifest_path)
    return None


def load(manifest_path: Path) -> Manifest:
    remote_git_server_schema = {"url": str}
    repo_schema = schema.Use(validate_repo)
    group_schema = {"repos": [str], schema.Optional("includes"): [str]}
    manifest_schema = schema.Schema(
        {
            "repos": [repo_schema],
            schema.Optional("gitlab"): remote_git_server_schema,
            schema.Optional("github_enterprise"): remote_git_server_schema,
            schema.Optional("groups"): {str: group_schema},
        }
    )
    parsed = tsrc.parse_config(manifest_path, manifest_schema)
    parsed = ManifestConfig(parsed)  # type: ignore
    as_manifest_config = cast(ManifestConfig, parsed)
    res = Manifest()
    res.load(as_manifest_config)
    return res
