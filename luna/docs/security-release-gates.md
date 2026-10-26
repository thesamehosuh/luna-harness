# Release security gates

Releases require a passing **Luna security checks / security** job as well as the existing
functional, archive-install and native-platform checks. A download is not ready because only
its application tests pass.

The gate audits every version in `uv.lock`, including versions selected only on other platforms,
with pinned pip-audit. It audits every tracked npm lock, including the documentation and optional
bridge packages. Network or audit-tool errors fail the gate. Patched direct dependencies and
reviewed transitive floors are recorded in the manifests and locks; optional lazy-install pins
must agree with the Python manifest.

The native launcher runs cargo-audit. Tauri's GTK3 line still requires glib 0.18.5; the upstream
mutable-output-pointer fix is backported in `apps/bootstrap-installer/src-tauri/vendor/glib`.
The gate checks that Cargo selects that local crate and that the patched source has its expected
hash before allowing the single matching RustSec exception. The ZIP reader uses the patched 9.x
line. The Rust scanner also reports upstream maintenance warnings for `proc-macro-error`,
`zbus_names`, `zvariant` and `zvariant_derive`; these require tracking with Tauri's Linux stack.
They are not dismissed as resolved vulnerabilities.

Gitleaks scans complete reachable Git history with findings redacted. Additional rules cover
Telegram tokens, account-session JWTs and OpenAI-shaped keys. A synthetic rejection probe proves
that all three rules run. `.gitleaksignore` contains exact inherited commit/file/rule/line
fingerprints for reviewed synthetic fixtures, public OAuth client identifiers and code falsely
matched as API credentials. It does not exempt entire directories or future commits. Token-shaped
fixture literals are constructed from fragments; documentation uses placeholders. Never add real
credentials to this baseline.

The October 26 containment made the repository private, withdrew both old alphas and disabled
Actions. Exact comparison against the operator's stored Luna/OpenCode/Codex credentials found no
matches in reachable source objects or either runtime archive. After restoring public visibility, the original alerts were recovered: both referenced inherited
synthetic credentials in `test_weak_credential_guard.py` and `test_sessions_export_md_cli.py`.
They were resolved as used in tests, and the literal fixtures were split into constructed strings. Credential rotation and private incident notes remain separate from
the public repository. No personal runtime state is shipped or used by the release checks.

The obsolete upstream Nix distribution was retired: it packaged Hermes/Electron with its own
stale build-tool lock and was not a Luna installation route. The supported installers are the
versioned desktop release assets described in the root README.
