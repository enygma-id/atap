<!-- SPDX-License-Identifier: AGPL-3.0-only -->
# Bounded native fuzzing

Run on Linux x86-64 with Python 3.12 and the optional fuzz extra:

```sh
uv sync --locked --extra dev --extra fuzz --python 3.12
mkdir -p .cache/fuzz
cp -R fuzz/corpus .cache/fuzz/
uv run python fuzz/fuzz_footprint_ids.py .cache/fuzz/corpus/footprint_ids -max_total_time=300 -max_len=16384 -timeout=10 -rss_limit_mb=2048
uv run python fuzz/fuzz_profile.py .cache/fuzz/corpus/profile -max_total_time=300 -max_len=16384 -timeout=10 -rss_limit_mb=2048
uv run python fuzz/fuzz_export.py .cache/fuzz/corpus/export -max_total_time=300 -max_len=16384 -timeout=10 -rss_limit_mb=2048
```

Footprint-ID fuzzing constructs valid synthetic geometry/envelopes and mutates
properties IDs and duplicate-ID cases through the real loader. It does not claim
to cover arbitrary geometry or malformed outer footprint envelopes. Profile
fuzzing checks arbitrary bounded JSON through the actual 0.6 schema. Export
fuzzing exercises validation and all writers, asserting canonical bytes unchanged.
Seeds are synthetic historical golden data only. Corpus extensions are local;
review any new seed before committing, and never commit crash artifacts blindly.

Expected validation errors (ATAP errors and ValueError) are accepted. Other
exceptions, crashes and timeouts are findings. JSON syntax/encoding and parser
nesting-limit errors are rejected before schema validation. Never suppress a
finding just to make fuzzing green. Report possible security issues privately;
fixes need a separate reviewed change. A clean bounded campaign is not proof
that no bugs exist. Weekly/dispatch campaigns retain crashes on failure.

Pull requests and pushes run the fixed synthetic seed corpus with each real
Atheris harness (`-runs=0`), checking native installation and entry-point execution.
These smoke checks do not replace the 300-second weekly/dispatch campaigns or
claim that random input campaigns are clean. Ordinary pytest jobs also install
Hypothesis through regenerated hash-verified development/NumPy 1 requirements.
