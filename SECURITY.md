# Security Policy

## How to report

Report suspected vulnerabilities privately using
[GitHub private vulnerability reporting](https://github.com/enygma-id/atap/security/advisories/new).
This is the designated security contact. Do not open a public Issue or pull request
with exploit details. Private vulnerability reporting is enabled.

Include the affected ATAP version or commit, platform and dependency versions,
a description of the impact, steps to reproduce, and a minimal synthetic input
or proof of concept when possible. Describe any known mitigation. Do not send
credentials, private datasets, production secrets or personal data; redact them
and agree a safe transfer method with the maintainers if needed.

## Response targets

Maintainers aim to acknowledge reports within 3 business days and complete initial
triage within 10 business days. Business days are measured in Western Indonesia
Time (WIB, UTC+7). Status updates are provided at least every 14 days while a
report is open.

After initial triage, remediation targets are 30 days for Critical/High severity,
60 days for Medium, and 90 days or the next release for Low severity. These are
targets, not guarantees; maintainers communicate delays and mitigations privately.

## Coordinated disclosure and credit

The coordinated disclosure target is 90 days from the initial report. Maintainers
and the reporter may agree to extend that period, or disclose sooner after a fix
has been released. Please coordinate publication to give users time to update.
Maintainers offer reporter credit with consent and respect requests for anonymity.

## Scope

Relevant security issues may include:

- arbitrary code execution;
- path traversal;
- unsafe archive/file handling;
- malicious raster or vector input handling;
- denial-of-service through crafted geometry;
- command injection;
- dependency or supply-chain compromise;
- credential leakage.

## Supported Versions

| Version | Security support |
|---|---|
| 0.3.x | Supported |
| < 0.3 | Unsupported; upgrade to a supported version |
