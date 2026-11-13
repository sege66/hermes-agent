"""Local (ki66) additions split out of the upstream-owned test_source_check.py."""

import pytest

from tests.hermes_cli.test_source_check import installation  # noqa: F401  (shared fixture)

# Same marker as the upstream module: the fixture serves channel records over loopback.
pytestmark = pytest.mark.real_release_channels


@pytest.mark.parametrize("owner", ["canonical", "other-checkout", "not-executable"])
@pytest.mark.parametrize("release,on", [("base", "head"), ("head", "base")])
def test_protected_checkout_offers_only_unmerged_releases(installation, tmp_path, owner, release, on):
    from hermes_cli.source_check import check_for_updates

    root, _linked, home, base, head, responses, _requests, git = installation
    shas = {"base": base, "head": head}
    bare = tmp_path / "origin.git"
    git("clone", "-q", "--bare", str(root), str(bare), cwd=tmp_path)
    git("tag", "v1.2.3", shas[release], cwd=bare)
    git("remote", "set-url", "origin", str(bare))
    git("checkout", "-q", "--detach", shas[on])
    api = "/repos/NousResearch/hermes-agent"
    responses[f"{api}/releases/latest"] = (200, {"draft": False, "prerelease": False, "tag_name": "v1.2.3"})
    responses[f"{api}/commits/v1.2.3"] = (200, {"sha": shas[release]})
    # Cache the upstream verdict before the protected owner becomes available.
    assert check_for_updates(install_root=root, home=home, channel="stable", force=True)["updateAvailable"]
    (home / "hermes-agent").symlink_to(root if owner != "other-checkout" else tmp_path)
    coordinator = home / "bin" / "hermes-update-coordinator"
    coordinator.parent.mkdir()
    coordinator.write_text("#!/bin/sh\nexit 0\n")
    coordinator.chmod(0o644 if owner == "not-executable" else 0o755)

    for force in (False, True):
        status = check_for_updates(install_root=root, home=home, channel="stable", force=force)
        integrated = owner == "canonical" and release == "base"
        assert status["targetSha"] == shas[release]
        assert status["updateAvailable"] is not integrated
        assert status["rollback"] is (release == "base" and not integrated)
        if integrated:
            assert status["behind"] == 0 and status["aheadOfRelease"] is True
