# SPDX-License-Identifier: AGPL-3.0-only
"""Prepare and check release assets; signing is performed by GitHub, never here."""
import argparse
import base64
import email.parser
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

REPOSITORY = "enygma-id/atap"
WORKFLOW = REPOSITORY + "/.github/workflows/release.yml"
PREDICATE = "https://slsa.dev/provenance/v1"
TAG = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def command(*args, cwd=None, binary=False):
    result = subprocess.run(args, cwd=cwd, capture_output=True, check=False)
    if result.returncode:
        raise ValueError(f"{args[0]} failed: {result.stderr.decode('utf-8', 'replace')[-1500:]}")
    return result.stdout if binary else result.stdout.decode("utf-8").strip()


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest() if hasattr(hashlib, "file_digest") else hashlib.sha256(stream.read()).hexdigest()


def safe_name(name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise ValueError("Unsafe artifact name")
    return name


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def prepare(repo, tag, rebuild, rehearsal, environment):
    if not TAG.fullmatch(tag):
        raise ValueError("Expected a stable tag such as v0.3.1")
    event, ref = environment.get("GITHUB_EVENT_NAME"), environment.get("GITHUB_REF")
    if not rehearsal:
        if environment.get("GITHUB_REPOSITORY") != REPOSITORY:
            raise ValueError("Release publishing is restricted to the canonical repository")
        if not ((event == "push" and ref == "refs/tags/" + tag) or
                (event == "workflow_dispatch" and ref == "refs/heads/main")):
            raise ValueError("Use a tag push or dispatch the reviewed main workflow")
    source = command("git", "rev-parse", "--verify", "refs/tags/" + tag + "^{commit}", cwd=repo)
    if not SHA.fullmatch(source):
        raise ValueError("Invalid tag commit")
    command("git", "merge-base", "--is-ancestor", source, "origin/main", cwd=repo)
    workflow_sha = environment.get("GITHUB_SHA", "")
    if not SHA.fullmatch(workflow_sha):
        raise ValueError("Invalid workflow-event commit")
    if event == "push" and not rehearsal and source != command("git", "rev-parse", workflow_sha + "^{commit}", cwd=repo):
        raise ValueError("The tag no longer matches the triggering commit")
    run_id, attempt = environment.get("GITHUB_RUN_ID", ""), environment.get("GITHUB_RUN_ATTEMPT", "")
    if not run_id.isdecimal() or not attempt.isdecimal():
        raise ValueError("Missing numeric workflow run identity")
    stem = "atap-" + tag + (f"-rebuild-{run_id}-{attempt}" if rebuild else "")
    return {"schema_version": 1, "repository": REPOSITORY, "tag": tag,
            "version": tag[1:], "source_sha": source, "rebuild": bool(rebuild),
            "purpose": "ci-rehearsal" if rehearsal else "release", "stem": stem,
            "workflow_ref": ref, "workflow_sha": workflow_sha,
            "run_id": run_id, "run_attempt": attempt,
            "build_requirements_sha256": digest(Path(repo) / "requirements/build.txt")}


def package(dist, out, context):
    dist, out = Path(dist), Path(out)
    files = sorted(dist.iterdir())
    # uv creates this exact VCS exclusion beside its build products.
    ignored = dist / ".gitignore"
    if ignored.is_file() and not ignored.is_symlink() and ignored.read_bytes().strip() == b"*":
        files = [f for f in files if f != ignored]
    if len(files) != 2 or any(not f.is_file() or f.is_symlink() for f in files):
        raise ValueError("Expected exactly one regular wheel and sdist")
    version = context["version"]
    expected = {f"atap-{version}-py3-none-any.whl", f"atap-{version}.tar.gz"}
    if {f.name for f in files} != expected:
        raise ValueError("Distribution filenames do not match the tag version")
    wheel = next(f for f in files if f.suffix == ".whl")
    with zipfile.ZipFile(wheel) as archive:
        data = archive.read(f"atap-{version}.dist-info/METADATA").decode("utf-8")
    metadata = email.parser.Parser().parsestr(data)
    if str(metadata["Name"]).lower() != "atap" or metadata["Version"] != version:
        raise ValueError("Wheel metadata does not match the tag")
    with tarfile.open(next(f for f in files if f.name.endswith(".tar.gz"))) as archive:
        member = archive.getmember(f"atap-{version}/PKG-INFO")
        if not member.isfile():
            raise ValueError("Invalid sdist metadata member")
        data = email.parser.Parser().parsestr(archive.extractfile(member).read().decode("utf-8"))
        if str(data["Name"]).lower() != "atap" or data["Version"] != version:
            raise ValueError("Sdist metadata does not match the tag")
    if out.exists() and any(out.iterdir()):
        raise ValueError("Release output directory must be empty")
    out.mkdir(parents=True, exist_ok=True)
    manifest = dict(context)
    manifest["distributions"] = {f.name: digest(f) for f in files}
    if context["rebuild"]:
        target = out / (safe_name(context["stem"]) + ".zip")
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for f in files:
                archive.write(f, f.name)
        assets = [target]
    else:
        import shutil
        assets = [Path(shutil.copyfile(f, out / f.name)) for f in files]
    manifest["assets"] = {f.name: digest(f) for f in assets}
    metadata_path = out / (safe_name(context["stem"]) + ".build.json")
    write_json(metadata_path, manifest)
    assets.append(metadata_path)
    checksums = out / (context["stem"] + ".SHA256SUMS")
    checksums.write_text("".join(f"{digest(f)}  {f.name}\n" for f in sorted(assets)), encoding="utf-8")
    return verify_files(out)


def verify_files(directory, tag=None, source_sha=None):
    directory = Path(directory)
    if any(f.is_symlink() or not f.is_file() for f in directory.iterdir()):
        raise ValueError("Release assets must be regular files")
    metadata_files = list(directory.glob("*.build.json"))
    if len(metadata_files) != 1:
        raise ValueError("Expected one build manifest")
    manifest = json.loads(metadata_files[0].read_text(encoding="utf-8"))
    stem = safe_name(manifest["stem"])
    if (manifest["schema_version"] != 1 or manifest["repository"] != REPOSITORY or
            not TAG.fullmatch(manifest["tag"]) or not SHA.fullmatch(manifest["source_sha"]) or
            manifest["version"] != manifest["tag"][1:] or
            not SHA.fullmatch(manifest["workflow_sha"]) or
            not DIGEST.fullmatch(manifest["build_requirements_sha256"])):
        raise ValueError("Invalid build identity")
    if (type(manifest["rebuild"]) is not bool or
            manifest["purpose"] not in ("release", "ci-rehearsal") or
            not str(manifest["run_id"]).isdecimal() or not str(manifest["run_attempt"]).isdecimal()):
        raise ValueError("Invalid build mode or workflow run identity")
    expected_stem = "atap-" + manifest["tag"] + (
        f"-rebuild-{manifest['run_id']}-{manifest['run_attempt']}" if manifest["rebuild"] else "")
    if stem != expected_stem:
        raise ValueError("Artifact stem does not match the build identity")
    if tag and tag != manifest["tag"] or source_sha and source_sha != manifest["source_sha"]:
        raise ValueError("Build manifest does not match the selected tag commit")
    if metadata_files[0].name != stem + ".build.json":
        raise ValueError("Manifest filename does not match its identity")
    assets = manifest["assets"]
    if not isinstance(assets, dict) or not assets:
        raise ValueError("Missing build assets")
    subjects = dict(assets)
    subjects[metadata_files[0].name] = digest(metadata_files[0])
    expected = set(subjects) | {stem + ".SHA256SUMS"}
    actual = {f.name for f in directory.iterdir()}
    if actual not in (expected, expected | {stem + ".intoto.jsonl"}):
        raise ValueError("Unexpected or missing release files")
    for name, value in subjects.items():
        path = directory / safe_name(name)
        if not DIGEST.fullmatch(value) or path.is_symlink() or not path.is_file() or digest(path) != value:
            raise ValueError("Artifact digest mismatch: " + name)
    if any(f.is_symlink() or not f.is_file() for f in directory.iterdir()):
        raise ValueError("Release assets must be regular files")
    expected_lines = {f"{value}  {name}" for name, value in subjects.items()}
    lines = (directory / (stem + ".SHA256SUMS")).read_text(encoding="utf-8").splitlines()
    if len(lines) != len(expected_lines) or set(lines) != expected_lines:
        raise ValueError("Checksums do not match the complete subject set")
    distributions = manifest["distributions"]
    expected_dist = {f"atap-{manifest['version']}-py3-none-any.whl", f"atap-{manifest['version']}.tar.gz"}
    if set(distributions) != expected_dist:
        raise ValueError("Unexpected distribution set")
    if manifest["rebuild"]:
        if set(assets) != {stem + ".zip"}:
            raise ValueError("Rebuilds must preserve historical assets in a unique bundle")
        with zipfile.ZipFile(directory / (stem + ".zip")) as archive:
            if len(archive.namelist()) != 2 or set(archive.namelist()) != expected_dist:
                raise ValueError("Unexpected rebuild bundle members")
            for name, value in distributions.items():
                if hashlib.sha256(archive.read(name)).hexdigest() != value:
                    raise ValueError("Rebuild distribution digest mismatch")
    elif assets != distributions:
        raise ValueError("Release distributions do not match the manifest")
    return manifest, subjects


def bundle_record(data, subjects):
    """Check subject structure only; gh performs cryptographic verification."""
    envelope = data["dsseEnvelope"]
    if not envelope.get("signatures") or not data.get("verificationMaterial"):
        raise ValueError("Missing signature or Sigstore verification material")
    statement = json.loads(base64.b64decode(envelope["payload"], validate=True))
    declared = {s["name"]: s["digest"]["sha256"] for s in statement["subject"]}
    if (statement["_type"] != "https://in-toto.io/Statement/v1" or
            statement["predicateType"] != PREDICATE or declared != subjects or
            len(statement["subject"]) != len(subjects)):
        raise ValueError("Attestation does not cover exactly these SLSA subjects")
    return json.dumps(data, separators=(",", ":")) + "\n"


def bundle_to_jsonl(directory, bundle):
    """Serialize a real GitHub bundle as JSONL; this does not verify signatures."""
    manifest, subjects = verify_files(directory)
    data = json.loads(Path(bundle).read_text(encoding="utf-8"))
    path = Path(directory) / (manifest["stem"] + ".intoto.jsonl")
    path.write_text(bundle_record(data, subjects), encoding="utf-8")
    return path


def verifier_version():
    text = command("gh", "--version")
    match = re.search(r"gh version (\d+)\.(\d+)\.(\d+)", text)
    if not match or tuple(map(int, match.groups())) < (2, 103, 3):
        raise ValueError("GitHub CLI 2.103.3 or newer is required for reviewed identity verification")
    print(text.splitlines()[0])


def verify_signature(directory, tag, source_sha, workflow_ref, workflow_sha):
    manifest, subjects = verify_files(directory, tag, source_sha)
    if (manifest["purpose"] != "release" or manifest["workflow_ref"] != workflow_ref or
            manifest["workflow_sha"] != workflow_sha):
        raise ValueError("Workflow identity mismatch or unsigned rehearsal")
    bundle = Path(directory) / (manifest["stem"] + ".intoto.jsonl")
    if not bundle.is_file():
        raise ValueError("Missing signed attestation bundle")
    verifier_version()
    for name in subjects:
        command("gh", "attestation", "verify", str(Path(directory) / name), "--repo", REPOSITORY,
                "--bundle", str(bundle), "--signer-workflow", WORKFLOW,
                "--source-ref", workflow_ref, "--source-digest", workflow_sha,
                "--predicate-type", PREDICATE, "--deny-self-hosted-runners")
    return manifest


def release_upload(directory, tag, source_sha, workflow_ref, workflow_sha):
    manifest = verify_signature(directory, tag, source_sha, workflow_ref, workflow_sha)
    tag_object = json.loads(command("gh", "api", f"repos/{REPOSITORY}/git/ref/tags/{tag}"))["object"]
    while tag_object["type"] == "tag":
        tag_object = json.loads(command("gh", "api", f"repos/{REPOSITORY}/git/tags/{tag_object['sha']}"))["object"]
    if tag_object["type"] != "commit" or tag_object["sha"] != source_sha:
        raise ValueError("Tag moved since the build; nothing will be uploaded")
    release = json.loads(command("gh", "api", f"repos/{REPOSITORY}/releases/tags/{tag}"))
    if release["tag_name"] != tag or release.get("immutable"):
        raise ValueError("Release is missing, mismatched or immutable")
    existing = {a["name"]: a for a in release["assets"]}
    pending = []
    for path in sorted(Path(directory).iterdir()):
        if path.name not in existing:
            pending.append(str(path))
            continue
        asset = existing[path.name]
        known = asset.get("digest")
        if not known:
            raw = command("gh", "api", f"repos/{REPOSITORY}/releases/assets/{asset['id']}",
                          "-H", "Accept: application/octet-stream", binary=True)
            known = "sha256:" + hashlib.sha256(raw).hexdigest()
        if known != "sha256:" + digest(path):
            raise ValueError("Refusing to replace an existing release asset: " + path.name)
    if pending:
        command("gh", "release", "upload", tag, *pending, "--repo", REPOSITORY)
    print(f"Verified {len(existing)} existing assets; uploaded {len(pending)} new assets for {manifest['tag']}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    sub.add_parser("verifier")
    p = sub.add_parser("prepare")
    p.add_argument("--repo-dir", type=Path, default=Path.cwd())
    p.add_argument("--tag", required=True)
    p.add_argument("--rebuild", action="store_true")
    p.add_argument("--rehearsal", action="store_true")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--github-output", type=Path)
    p = sub.add_parser("package")
    p.add_argument("--dist", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--context", type=Path, required=True)
    p = sub.add_parser("bundle")
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--bundle", type=Path, required=True)
    for name in ("check", "verify", "upload"):
        p = sub.add_parser(name)
        p.add_argument("--directory", type=Path, required=True)
        p.add_argument("--tag", required=True)
        p.add_argument("--source-sha", required=True)
        if name != "check":
            p.add_argument("--workflow-ref", required=True)
            p.add_argument("--workflow-sha", required=True)
    args = parser.parse_args()
    try:
        if args.operation == "verifier":
            verifier_version()
        elif args.operation == "prepare":
            context = prepare(args.repo_dir, args.tag, args.rebuild, args.rehearsal, os.environ)
            write_json(args.out, context)
            if args.github_output:
                with args.github_output.open("a", encoding="utf-8") as out:
                    for key in ("tag", "source_sha", "version", "stem"):
                        out.write(f"{key}={context[key]}\n")
        elif args.operation == "package":
            package(args.dist, args.out, json.loads(args.context.read_text(encoding="utf-8")))
        elif args.operation == "bundle":
            print(bundle_to_jsonl(args.directory, args.bundle))
        elif args.operation == "check":
            verify_files(args.directory, args.tag, args.source_sha)
        else:
            function = verify_signature if args.operation == "verify" else release_upload
            function(args.directory, args.tag, args.source_sha, args.workflow_ref, args.workflow_sha)
    except (ValueError, KeyError, OSError, zipfile.BadZipFile, tarfile.TarError) as exc:
        parser.exit(1, f"Release validation failed: {exc}\n")


if __name__ == "__main__":
    main()
