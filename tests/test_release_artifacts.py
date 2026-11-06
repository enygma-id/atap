# SPDX-License-Identifier: AGPL-3.0-only
"""Release boundaries: metadata, corruption, source binding and non-overwrite."""
import importlib.util
import io
import json
import tarfile
import zipfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "release_artifacts", Path(__file__).resolve().parents[1] / "tools/release_artifacts.py"
)
release = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release)


@pytest.fixture
def context():
    return {"schema_version": 1, "repository": "enygma-id/atap", "tag": "v0.3.0",
            "version": "0.3.0", "source_sha": "a" * 40, "workflow_sha": "b" * 40,
            "workflow_ref": "refs/heads/main", "run_id": "123", "run_attempt": "1",
            "rebuild": False, "purpose": "release", "stem": "atap-v0.3.0",
            "build_requirements_sha256": "c" * 64}


@pytest.fixture
def distributions(tmp_path):
    root = tmp_path / "dist"
    root.mkdir()
    info = b"Metadata-Version: 2.3\nName: atap\nVersion: 0.3.0\n"
    with zipfile.ZipFile(root / "atap-0.3.0-py3-none-any.whl", "w") as out:
        out.writestr("atap-0.3.0.dist-info/METADATA", info)
    with tarfile.open(root / "atap-0.3.0.tar.gz", "w:gz") as out:
        member = tarfile.TarInfo("atap-0.3.0/PKG-INFO")
        member.size = len(info)
        out.addfile(member, io.BytesIO(info))
    return root


@pytest.fixture
def assets(tmp_path, distributions, context):
    root = tmp_path / "assets"
    release.package(distributions, root, context)
    return root


def test_real_metadata_and_rebuild_preserve_distribution_bytes(tmp_path, distributions, context):
    original = {f.name: f.read_bytes() for f in distributions.iterdir()}
    context.update(rebuild=True, stem="atap-v0.3.0-rebuild-123-1")
    manifest, subjects = release.package(distributions, tmp_path / "rebuild", context)
    assert len(subjects) == 2
    with zipfile.ZipFile(tmp_path / "rebuild" / (context["stem"] + ".zip")) as archive:
        assert {name: archive.read(name) for name in archive.namelist()} == original
    assert manifest["source_sha"] == "a" * 40


@pytest.mark.parametrize("changed", ["wheel", "metadata", "checksum", "extra", "missing"])
def test_corruption_is_rejected(assets, changed):
    if changed == "wheel":
        next(assets.glob("*.whl")).write_bytes(b"modified")
    elif changed == "metadata":
        p = next(assets.glob("*.build.json"))
        d = json.loads(p.read_text())
        d["source_sha"] = "d" * 40
        p.write_text(json.dumps(d))
    elif changed == "checksum":
        next(assets.glob("*.SHA256SUMS")).write_text("")
    elif changed == "extra":
        (assets / "unexpected.sh").write_text("untrusted")
    else:
        next(assets.glob("*.whl")).unlink()
    with pytest.raises(ValueError):
        release.verify_files(assets, "v0.3.0", "a" * 40)


@pytest.mark.parametrize("name", ["../x", "/tmp/x", "x/y", "x\\y", "x\nname", "--option", "$(x)", ""])
def test_artifact_path_injection_is_rejected(name):
    with pytest.raises(ValueError):
        release.safe_name(name)


@pytest.mark.parametrize("tag", ["main", "../main", "v0.3.0\nother", "v0.3.0;echo x", "--help", "v01.2.3", "v0.3.0-rc1"])
def test_invalid_tag_rejected_before_git(tag, monkeypatch):
    monkeypatch.setattr(release, "command", lambda *a, **k: pytest.fail("git must not run"))
    with pytest.raises(ValueError, match="stable tag"):
        release.prepare(Path.cwd(), tag, False, False, {})


def test_unsigned_and_rehearsal_assets_cannot_be_published(assets):
    with pytest.raises(ValueError, match="Missing signed"):
        release.verify_signature(assets, "v0.3.0", "a" * 40, "refs/heads/main", "b" * 40)


def test_rehearsal_identity_rejected_before_any_crypto_call(tmp_path, distributions, context, monkeypatch):
    context["purpose"] = "ci-rehearsal"
    directory = tmp_path / "rehearsal"
    release.package(distributions, directory, context)
    monkeypatch.setattr(release, "command", lambda *a, **k: pytest.fail("no service calls allowed"))
    with pytest.raises(ValueError, match="unsigned rehearsal"):
        release.verify_signature(directory, "v0.3.0", "a" * 40, "refs/heads/main", "b" * 40)


def test_source_and_workflow_mismatches_rejected_before_verifier(assets, monkeypatch):
    monkeypatch.setattr(release, "command", lambda *a, **k: pytest.fail("no verifier call expected"))
    with pytest.raises(ValueError, match="selected tag"):
        release.verify_signature(assets, "v0.3.0", "d" * 40, "refs/heads/main", "b" * 40)
    with pytest.raises(ValueError, match="Workflow identity"):
        release.verify_signature(assets, "v0.3.0", "a" * 40, "refs/heads/other", "b" * 40)


def test_output_directory_not_overwritten(distributions, assets, context):
    old = {p.name: p.read_bytes() for p in assets.iterdir()}
    with pytest.raises(ValueError, match="must be empty"):
        release.package(distributions, assets, context)
    assert old == {p.name: p.read_bytes() for p in assets.iterdir()}


def test_wrong_distribution_version_rejected_before_packaging(distributions, tmp_path, context):
    context.update(tag="v0.3.1", version="0.3.1", stem="atap-v0.3.1")
    with pytest.raises(ValueError, match="filenames"):
        release.package(distributions, tmp_path / "out", context)


def test_uv_build_gitignore_is_not_a_distribution(distributions, tmp_path, context):
    (distributions / ".gitignore").write_text("*")
    release.package(distributions, tmp_path / "out", context)
    assert not (tmp_path / "out/.gitignore").exists()


def test_unexpected_hidden_build_file_is_rejected(distributions, tmp_path, context):
    (distributions / ".other").write_text("unexpected")
    with pytest.raises(ValueError):
        release.package(distributions, tmp_path / "out", context)


def test_unsigned_bundle_is_rejected():
    with pytest.raises(ValueError, match="Missing signature"):
        release.bundle_record({"dsseEnvelope": {"signatures": []}}, {})


@pytest.mark.parametrize("version", ["2.100.0", "2.103.2", "unrecognized"])
def test_old_or_unknown_verifier_is_rejected(monkeypatch, version):
    monkeypatch.setattr(release, "command", lambda *a: "gh version " + version)
    with pytest.raises(ValueError, match="2.103.3"):
        release.verifier_version()


def test_reviewed_verifier_version_is_accepted(monkeypatch):
    monkeypatch.setattr(release, "command", lambda *a: "gh version 2.103.3 (2026-10-26)")
    release.verifier_version()


def upload_adapter(monkeypatch, assets, context, *, moved=False, conflict=False, present=False):
    """Stub authenticated service calls, not signing or attestation generation."""
    calls = []
    monkeypatch.setattr(release, "verify_signature", lambda *args: context)
    existing = []
    if conflict or present:
        existing = [{"name": f.name, "digest": "sha256:" + ("d" * 64 if conflict else release.digest(f))}
                    for f in assets.iterdir()]

    def api(*args, **kwargs):
        calls.append(args)
        if "git/ref/tags/" in args[-1]:
            return json.dumps({"object": {"type": "commit", "sha": ("d" if moved else "a") * 40}})
        if "releases/tags/" in args[-1]:
            return json.dumps({"tag_name": "v0.3.0", "assets": existing})
        return ""

    monkeypatch.setattr(release, "command", api)
    return calls


def test_changed_tag_blocks_every_upload(assets, context, monkeypatch):
    calls = upload_adapter(monkeypatch, assets, context, moved=True)
    with pytest.raises(ValueError, match="Tag moved"):
        release.release_upload(assets, "v0.3.0", "a" * 40, "refs/heads/main", "b" * 40)
    assert not any("upload" in c for c in calls)


def test_different_existing_bytes_never_clobbered(assets, context, monkeypatch):
    calls = upload_adapter(monkeypatch, assets, context, conflict=True)
    with pytest.raises(ValueError, match="Refusing to replace"):
        release.release_upload(assets, "v0.3.0", "a" * 40, "refs/heads/main", "b" * 40)
    assert not any("upload" in c for c in calls)


def test_identical_assets_are_idempotent_and_new_upload_has_no_clobber(assets, context, monkeypatch):
    calls = upload_adapter(monkeypatch, assets, context, present=True)
    release.release_upload(assets, "v0.3.0", "a" * 40, "refs/heads/main", "b" * 40)
    assert not any("upload" in c for c in calls)
    calls = upload_adapter(monkeypatch, assets, context)
    release.release_upload(assets, "v0.3.0", "a" * 40, "refs/heads/main", "b" * 40)
    uploads = [c for c in calls if "upload" in c]
    assert len(uploads) == 1 and "--clobber" not in uploads[0]


def test_unreviewed_dispatch_and_wrong_repository_rejected():
    for env in ({"GITHUB_REPOSITORY": "other/atap"},
                {"GITHUB_REPOSITORY": "enygma-id/atap", "GITHUB_EVENT_NAME": "workflow_dispatch",
                 "GITHUB_REF": "refs/heads/unreviewed"}):
        with pytest.raises(ValueError):
            release.prepare(Path.cwd(), "v0.3.0", False, False, env)
