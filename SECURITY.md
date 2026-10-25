# Luna security policy

Report vulnerabilities privately through
[GitHub private vulnerability reporting](https://github.com/thesamehosuh/luna-harness/security/advisories/new).
Do not send Luna reports to the upstream Hermes maintainers. No bounty program is offered.

Include the affected release/commit, operating system, reproducible steps, expected boundary and
impact. Use synthetic credentials and chats. Do not include real tokens or personal conversation
history. This project is an alpha; fixes target the latest release.

## Trust model

Luna is self-hosted personal software running with its owner's permissions. The owner's DM and
local dashboard expose powerful assistant tools, including files and terminal access. Run it under
an account with only the access you intend to grant. Installed plugins, skills and model providers
must also be trusted; model instructions are not a sandbox.

Group chat has additional code-enforced capability, identity, recipient/topic, privacy and output
restrictions. Identity comes from transport IDs. Untrusted group text must not become privileged
instructions, change the selected recipient or gain owner tools. Report a reproducible bypass of
these controls, cross-profile data exposure, secret leakage, unauthorized dashboard/native access,
unsafe archive extraction or unauthorized file/tool execution as a security issue.

The dashboard binds locally and uses authenticated sessions; native launcher commands are limited
to its own bootstrap window. Do not expose the dashboard publicly without a separately secured
access layer. Honcho runs locally when enabled. Chat and wake content goes to the model endpoints
the owner selects; stored-score replay makes no model requests. Review providers before use.

Release files carry checksums and build provenance. Alpha macOS/Windows installers are unsigned;
checksums do not provide operating-system publisher signing.
