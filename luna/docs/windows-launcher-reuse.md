# Native launcher reuse audit

Luna uses the vendored Hermes native Windows backend. WSL is not a prerequisite for chat.
Docker is needed only when the owner enables local Honcho memory.

| Existing component | Luna integration |
| --- | --- |
| `apps/bootstrap-installer` (Rust/Tauri 2) | Keep the native shell, WebView2 provisioning, console decoding and progress patterns. Replace the source-checkout/Electron handoff with a verified Luna release and the local dashboard in the same window. |
| `scripts/install.ps1` | Reuse managed uv/Python and Windows process conventions. Do not run its repository, global PATH, Electron or gateway stages against a Luna installation. |
| `hermes_cli/web_server_chat.py`, `win_pty_bridge.py` | Already select ConPTY on Windows. Keep the current embedded TUI. The POSIX-only `pty_bridge.py` is not evidence that Windows chat needs a new implementation. |
| `apps/desktop/electron/backend-*` | Reuse readiness, per-home ownership and bounded shutdown contracts in the Rust launcher. The Electron renderer is not shipped. |
| `hermes_cli/_subprocess_compat.py`, `gateway/control_socket.py` | Keep existing hidden Windows process/tree cleanup and named-pipe gateway control. |
| `hermes_state_repair.py` | Reuse its `msvcrt` byte-range lock protocol for Luna's settings and native worker leases; fail closed on unsupported/error cases. |
| `luna/deploy/*`, `product_runtime.py` | Retain staged releases and rollback. Add native Windows runtime paths and publication that does not require privileged symlink creation. |

The audited source is the vendored version, not today's upstream installer: current upstream
documentation can describe newer Python/packaging behavior than this tree supports. Luna keeps
its Python 3.11–3.13 contract and prebuilt web/TUI assets.

Initial isolated checks: **47 passed, 20 skipped** across Windows PTY, gateway control, hidden
subprocess flags and PowerShell installer regressions. Skips require real Windows/PowerShell;
Linux mocks/static checks do not certify native Windows installation.

Implementation and release gates are tracked in `beginner-setup-plan.md`. All development installs
use disposable homes; the owner's stopped legacy homes and services remain untouched.

Primary reference: [Hermes native Windows guide](https://hermes-agent.nousresearch.com/docs/user-guide/windows-native).
