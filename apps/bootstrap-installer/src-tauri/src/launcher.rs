//! Luna's release bootstrap and dashboard lifetime. No repository clone or UI build.
use anyhow::{bail, Context, Result};
use fs2::FileExt;
use futures::StreamExt;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{fs, io::{Read, Write}, path::{Path, PathBuf}, process::Stdio,
    sync::{Arc, atomic::{AtomicBool, Ordering}}, time::{Duration, Instant}};
use tauri::{Emitter, Manager};
use tokio::{io::BufReader, process::{Child, Command}, sync::Mutex};
#[path = "desktop_controls.rs"]
mod controls;
#[cfg(target_os = "linux")]
#[path = "appimage_menu.rs"]
mod appimage_menu;

#[derive(Clone, Deserialize)]
struct Download { url: String, sha256: String }
#[derive(Deserialize)]
struct Release { version: String, runtime: Download }
#[derive(Clone, Serialize)]
struct Progress {
    stage: String, detail: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    completed_bytes: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    total_bytes: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    bytes_per_second: Option<f64>,
}
struct State {
    busy: Mutex<()>, cancelled: AtomicBool, backend: Mutex<Option<Child>>,
    home: PathBuf, preferences: std::sync::Mutex<controls::Preferences>,
    tray_available: AtomicBool, hidden_launch: AtomicBool,
    session: Mutex<Option<controls::DashboardSession>>, companion_control: Mutex<()>,
}
struct DesktopLock { _handle: fs::File }

fn home() -> Result<PathBuf> {
    // HERMES_HOME is intentionally not inherited from another installed product.
    let arguments: Vec<String> = std::env::args().collect();
    let explicit = arguments.windows(2).find(|pair| pair[0] == "--luna-home").map(|pair| std::ffi::OsString::from(&pair[1]));
    if let Some(value) = explicit.or_else(|| std::env::var_os("LUNA_HOME")).filter(|s| !s.is_empty()) {
        let path = PathBuf::from(value);
        if !path.is_absolute() { bail!("LUNA_HOME must be an absolute path") }
        return Ok(path);
    }
    let base = if cfg!(windows) {
        dirs::data_local_dir().context("Cannot locate your local data directory")?.join("Luna")
    } else {
        dirs::home_dir().context("Cannot locate your home directory")?.join(".luna")
    };
    Ok(clean_home(base))
}

fn clean_home(base: PathBuf) -> PathBuf {
    // Never silently adopt a legacy character, credentials or chat history.
    if !base.exists() || fs::read_dir(&base).map(|mut entries| entries.next().is_none()).unwrap_or(false) || base.join("current-release.json").exists() || base.join(".desktop-installation.json").exists() {
        return base
    }
    let name = base.file_name().unwrap().to_string_lossy();
    for index in 1..100 {
        let candidate = base.with_file_name(if index == 1 { format!("{name}-desktop") } else { format!("{name}-desktop-{index}") });
        if !candidate.exists() || candidate.join("current-release.json").exists() || candidate.join(".desktop-installation.json").exists() { return candidate }
    }
    base.with_file_name(format!("{name}-desktop-{}", uuid::Uuid::new_v4()))
}

fn progress(app: &tauri::AppHandle, stage: &str, detail: &str) {
    let _ = app.emit("luna-progress", Progress { stage: stage.into(), detail: detail.into(), completed_bytes: None, total_bytes: None, bytes_per_second: None });
}
fn transfer_progress(app: &tauri::AppHandle, stage: &str, received: u64, total: Option<u64>, speed: f64) {
    let _ = app.emit("luna-progress", Progress { stage: stage.into(), detail: if stage == "runtime" { "Downloading the Python installer…" } else { "Downloading the Luna runtime…" }.into(), completed_bytes: Some(received), total_bytes: total, bytes_per_second: Some(speed) });
}

fn setup_stage_detail(stage: &str) -> &'static str {
    match stage {
        "dependencies" => "Installing Python and Luna’s dependencies…",
        "chat-runtime" => "Preparing your chat runtime…",
        "native-tools" => "Setting up native tools…",
        "personal-home" => "Preparing your profile…",
        "ready" => "Installation verified. Finishing up…",
        _ => "Preparing Luna…",
    }
}
fn check_cancel(state: &State) -> Result<()> {
    if state.cancelled.load(Ordering::Relaxed) { bail!("Setup cancelled. Open Luna again to resume.") }
    Ok(())
}
// A stalled server must not make Cancel (or window close) wait for the read timeout.
async fn cancellable<T>(cancelled: &AtomicBool, future: impl std::future::Future<Output = T>) -> Result<T> {
    tokio::pin!(future);
    loop {
        if cancelled.load(Ordering::Relaxed) { bail!("Setup cancelled. Open Luna again to resume.") }
        tokio::select! {
            result = &mut future => return Ok(result),
            _ = tokio::time::sleep(Duration::from_millis(100)) => {},
        }
    }
}
fn digest(path: &Path) -> Result<String> {
    let mut file = fs::File::open(path)?;
    let mut hash = Sha256::new();
    let mut buf = [0; 262144];
    loop { let n = file.read(&mut buf)?; if n == 0 { break } hash.update(&buf[..n]); }
    Ok(format!("{:x}", hash.finalize()))
}

async fn download(app: &tauri::AppHandle, state: &State, spec: &Download, target: &Path, limit: u64, stage: &str) -> Result<()> {
    if spec.sha256.len() != 64 || !spec.sha256.bytes().all(|b| b.is_ascii_hexdigit()) {
        bail!("This launcher has an invalid release checksum")
    }
    if target.is_file() && digest(target)? == spec.sha256 { return Ok(()) }
    let url = reqwest::Url::parse(&spec.url)?;
    if url.scheme() != "https" { bail!("Release downloads require HTTPS") }
    let partial = target.with_extension("partial");
    let client = reqwest::Client::builder().connect_timeout(Duration::from_secs(10)).read_timeout(Duration::from_secs(30)).timeout(Duration::from_secs(900)).build()?;
    for attempt in 0..3 {
        check_cancel(state)?;
        let offset = fs::metadata(&partial).map(|m| m.len()).unwrap_or(0);
        let mut request = client.get(url.clone());
        if offset > 0 { request = request.header("Range", format!("bytes={offset}-")); }
        let response = match cancellable(&state.cancelled, request.send()).await?.and_then(|r| r.error_for_status()) {
            Ok(r) => r,
            Err(e) if attempt < 2 => { progress(app, stage, "Connection interrupted; retrying…"); let _ = e; continue },
            Err(e) => return Err(e).context("Download interrupted. Retry to resume"),
        };
        let resumed = response.status() == reqwest::StatusCode::PARTIAL_CONTENT &&
            response.headers().get("content-range").and_then(|v|v.to_str().ok())
                .map(|v|v.starts_with(&format!("bytes {offset}-"))).unwrap_or(false);
        let mut received = if resumed { offset } else { 0 };
        let total = response.content_length().and_then(|length| length.checked_add(received));
        if total.is_some_and(|size| size > limit) { bail!("Download exceeds this release's size limit") }
        let started = Instant::now();
        let initial_received = received;
        transfer_progress(app, stage, received, total, 0.0);
        let mut output = fs::OpenOptions::new().create(true).write(true).append(resumed).truncate(!resumed).open(&partial)?;
        let mut chunks = response.bytes_stream();
        let mut failure = None;
        let mut last = Instant::now();
        while let Some(chunk) = cancellable(&state.cancelled, chunks.next()).await? {
            check_cancel(state)?;
            let bytes = match chunk { Ok(b) => b, Err(e) => { failure = Some(e); break } };
            received += bytes.len() as u64;
            if received > limit { bail!("Download exceeds this release's size limit") }
            output.write_all(&bytes)?;
            if last.elapsed() > Duration::from_millis(400) {
                let speed = (received - initial_received) as f64 / started.elapsed().as_secs_f64().max(0.001);
                transfer_progress(app, stage, received, total, speed); last = Instant::now();
            }
        }
        output.sync_all()?; drop(output);
        if let Some(e) = failure { if attempt < 2 { continue } return Err(e).context("Download interrupted; retry to resume") }
        progress(app, stage, "Checking the download’s integrity…");
        if digest(&partial)? != spec.sha256 { fs::remove_file(&partial)?; bail!("Download checksum did not match. Please retry.") }
        if target.exists() { fs::remove_file(target)?; }
        fs::rename(&partial, target)?;
        return Ok(())
    }
    bail!("Download could not finish. Please retry.")
}

fn unpack(archive: &Path, target: &Path, uv_only: bool) -> Result<()> {
    fs::create_dir_all(target)?;
    let mut total = 0u64;
    if archive.extension().and_then(|s|s.to_str()) == Some("zip") {
        let mut zip = zip::ZipArchive::new(fs::File::open(archive)?)?;
        for index in 0..zip.len() {
            let mut entry = zip.by_index(index)?;
            if entry.is_dir() { continue }
            let path = entry.enclosed_name().context("Unsafe archive path")?;
            if path.file_name().and_then(|s|s.to_str()) != Some("uv.exe") { continue }
            total += entry.size(); if total > 200_000_000 { bail!("Runtime archive is too large") }
            std::io::copy(&mut entry, &mut fs::File::create(target.join("uv.exe"))?)?;
        }
        return Ok(())
    }
    let decoder = flate2::read::GzDecoder::new(fs::File::open(archive)?);
    for entry in tar::Archive::new(decoder).entries()? {
        let mut entry = entry?;
        let path = entry.path()?.into_owned();
        if path.components().any(|c| !matches!(c, std::path::Component::Normal(_))) { bail!("Unsafe archive path") }
        if entry.header().entry_type().is_dir() { continue }
        if !entry.header().entry_type().is_file() { bail!("Release archives must contain regular files") }
        total += entry.size(); if total > 2_000_000_000 { bail!("Release archive is too large") }
        let relative: PathBuf = if uv_only {
            if path.file_name().and_then(|s|s.to_str()) != Some("uv") { continue }
            "uv".into()
        } else { path.components().skip(1).collect() };
        if relative.as_os_str().is_empty() { bail!("Invalid release layout") }
        let destination = target.join(relative);
        fs::create_dir_all(destination.parent().unwrap())?;
        std::io::copy(&mut entry, &mut fs::File::create(&destination)?)?;
        #[cfg(unix)] {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&destination, fs::Permissions::from_mode(entry.header().mode()? & 0o755))?;
        }
    }
    Ok(())
}

fn command(program: &Path, home: &Path) -> Command {
    let mut cmd = Command::new(program);
    cmd.env("HERMES_HOME", home).env("LUNA_HOME", home)
        .env("UV_PYTHON_INSTALL_DIR", home.join("runtime/python"))
        .env("UV_CACHE_DIR", home.join("cache/uv"))
        .env("PYTHONUTF8", "1").env("PYTHONIOENCODING", "utf-8")
        .env_remove("PYTHONHOME").env_remove("PYTHONPATH").env_remove("VIRTUAL_ENV")
        .kill_on_drop(true);
    #[cfg(windows)] { cmd.creation_flags(0x08000000); }
    #[cfg(unix)] { cmd.process_group(0); }
    cmd
}
async fn stop(child: &mut Child) {
    if child.try_wait().ok().flatten().is_some() { return }
    if let Some(pid) = child.id() {
        #[cfg(unix)] { unsafe { libc::kill(-(pid as i32), libc::SIGTERM); } }
        #[cfg(windows)] {
            let mut kill = Command::new("taskkill.exe"); kill.creation_flags(0x08000000);
            let _ = tokio::time::timeout(Duration::from_secs(5), kill.args(["/T", "/F", "/PID", &pid.to_string()]).status()).await;
        }
    }
    if tokio::time::timeout(Duration::from_secs(5), child.wait()).await.is_err() {
        #[cfg(unix)] { if let Some(pid) = child.id() { unsafe { libc::kill(-(pid as i32), libc::SIGKILL); } } }
        let _ = child.kill().await;
    }
}
async fn run_stage(app: &tauri::AppHandle, state: &State, cmd: &mut Command) -> Result<()> {
    let mut child = cmd.stdout(Stdio::piped()).stderr(Stdio::piped()).spawn()?;
    let mut stdout = BufReader::new(child.stdout.take().unwrap());
    let mut buffer = Vec::new();
    let mut stdout_open = true;
    // Drain stderr without forwarding package URLs or potential credential-bearing diagnostics.
    let err = child.stderr.take().unwrap();
    let drain = tokio::spawn(async move { let _ = tokio::io::copy(&mut BufReader::new(err), &mut tokio::io::sink()).await; });
    let deadline = Instant::now() + Duration::from_secs(1200);
    loop {
        if state.cancelled.load(Ordering::Relaxed) || Instant::now() > deadline {
            stop(&mut child).await; drain.abort(); check_cancel(state)?; bail!("Runtime setup timed out. Retry to resume.")
        }
        if let Some(status) = child.try_wait()? {
            drain.abort();
            if !status.success() { bail!("Runtime setup failed. Retry keeps your existing installation and personal data.") }
            return Ok(())
        }
        tokio::select! {
            line = crate::powershell::read_decoded_line(&mut stdout, &mut buffer), if stdout_open => match line {
                Ok(Some(line)) => if let Some(stage) = line.strip_prefix("LUNA_STAGE ") { progress(app, stage, setup_stage_detail(stage)); },
                Ok(None) => stdout_open = false,
                Err(e) => { stop(&mut child).await; drain.abort(); return Err(e.into()) },
            },
            _ = tokio::time::sleep(Duration::from_millis(100)) => {},
        }
    }
}

fn selected(home: &Path) -> Result<Option<PathBuf>> {
    let marker = home.join("current-release.json");
    if !marker.is_file() { return Ok(None) }
    let data: serde_json::Value = serde_json::from_slice(&fs::read(marker)?)?;
    let release = home.join(data["path"].as_str().context("Invalid release pointer")?).canonicalize()?;
    if release.parent() != Some(home.join("releases").canonicalize()?.as_path()) || !release.join(".ready").is_file() {
        bail!("The installed runtime needs repair")
    }
    Ok(Some(release))
}

async fn prepare(app: &tauri::AppHandle, state: &State, home: &Path, repair: bool) -> Result<PathBuf> {
    if cfg!(all(windows, target_arch="aarch64")) {
        bail!("Use Luna's Windows x64 app on this machine. Native Windows ARM support is waiting for the backend's binary dependencies.")
    }
    if !repair { if let Some(root) = selected(home)? { return Ok(root) } }
    let descriptor = option_env!("LUNA_RELEASE_DESCRIPTOR_JSON").context("This development launcher has no published Luna release. Build it with LUNA_RELEASE_DESCRIPTOR pointing to a generated release descriptor.")?;
    let release: Release = serde_json::from_str(descriptor)?;
    if let Ok(Some(current)) = selected(home) {
        let data: serde_json::Value = serde_json::from_slice(&fs::read(current.join("luna-release.json"))?)?;
        if let (Ok(current), Ok(next)) = (semver::Version::parse(data["version"].as_str().unwrap_or("")), semver::Version::parse(&release.version)) {
            if current > next { bail!("This launcher is older than the installed runtime. Download the current Luna app to repair it; compatible rollback is available in System.") }
        }
    }
    let cache = home.join("cache/launcher"); fs::create_dir_all(&cache)?;
    let archive = cache.join("luna-runtime.tar.gz");
    progress(app, "download", &format!("Downloading Luna {}…", release.version));
    download(app, state, &release.runtime, &archive, 500_000_000, "download").await?;
    let root = home.join("releases").join(uuid::Uuid::new_v4().to_string());
    unpack(&archive, &root, false)?;
    let metadata: serde_json::Value = serde_json::from_slice(&fs::read(root.join("luna-release.json"))?)?;
    if metadata["version"] != release.version { bail!("Release version does not match this launcher") }
    let uv_catalog: serde_json::Value = serde_json::from_str(include_str!("../uv-releases.json"))?;
    let os = if cfg!(windows) { "windows" } else if cfg!(target_os="macos") { "darwin" } else { "linux" };
    let arch = if cfg!(target_arch="aarch64") { "arm64" } else if cfg!(target_arch="x86_64") { "x64" } else { bail!("Unsupported CPU") };
    let uv_spec: Download = serde_json::from_value(uv_catalog["targets"][format!("{os}-{arch}")].clone())?;
    let uv_archive = cache.join(if cfg!(windows) {"uv.zip"} else {"uv.tar.gz"});
    progress(app, "runtime", "Preparing Python…");
    download(app, state, &uv_spec, &uv_archive, 100_000_000, "runtime").await?;
    let uv_root = home.join("runtime/uv"); unpack(&uv_archive, &uv_root, true)?;
    let uv = uv_root.join(if cfg!(windows) {"uv.exe"} else {"uv"});
    run_stage(app, state, command(&uv, home).args(["run", "--no-project", "--managed-python", "--python", "3.11"])
        .arg(root.join("luna/deploy/desktop_install.py")).arg("--home").arg(home).arg("--uv").arg(&uv)).await?;
    selected(home)?.context("Runtime installation did not publish a verified release")
}

async fn start(app: tauri::AppHandle, state: &State, repair: bool) -> Result<()> {
    let _operation = state.busy.try_lock().context("Luna is already starting")?;
    if state.backend.lock().await.is_some() { bail!("Luna is already open") }
    state.cancelled.store(false, Ordering::Relaxed);
    let home = home()?.canonicalize()?;
    let root = prepare(&app, state, &home, repair).await?;
    check_cancel(state)?;
    progress(&app, "dashboard", "Opening your dashboard…");
    let nonce = uuid::Uuid::new_v4().to_string();
    let token = uuid::Uuid::new_v4().to_string() + &uuid::Uuid::new_v4().to_string();
    let ready = home.join("cache/launcher").join(format!("ready-{nonce}.json"));
    fs::create_dir_all(ready.parent().unwrap())?;
    let python = root.join(if cfg!(windows) {"venv/Scripts/python.exe"} else {"venv/bin/python"});
    let mut child = command(&python, &home).arg("-m").arg("luna_cli.desktop")
        .current_dir(&root).env("LUNA_DESKTOP_NONCE", &nonce)
        .env("HERMES_DASHBOARD_SESSION_TOKEN", &token).env("HERMES_DESKTOP_READY_FILE", &ready)
        .env("HERMES_PARENT_PID", std::process::id().to_string())
        .stdin(Stdio::piped()).stdout(Stdio::null()).stderr(Stdio::null()).spawn()?;
    let expected_version: serde_json::Value = serde_json::from_slice(&fs::read(root.join("luna-release.json"))?)?;
    let outcome: Result<reqwest::Url> = async {
        let client = reqwest::Client::builder().no_proxy().timeout(Duration::from_secs(3)).build()?;
        let deadline = Instant::now() + Duration::from_secs(120);
        loop {
            check_cancel(state)?;
            if child.try_wait()?.is_some() { bail!("The dashboard could not start. Retry or repair the runtime.") }
            if Instant::now() > deadline { bail!("The dashboard took too long to start. Please retry.") }
            if let Ok(bytes) = fs::read(&ready) {
                if let Ok(data) = serde_json::from_slice::<serde_json::Value>(&bytes) {
                    if let Some(port) = data["port"].as_u64().filter(|p| *p>0 && *p<65536) {
                        let base = format!("http://127.0.0.1:{port}");
                        if let Ok(response) = client.get(format!("{base}/api/luna/desktop/identity")).bearer_auth(&token).send().await {
                            if response.status().is_success() {
                                let identity: serde_json::Value = serde_json::from_slice(&response.bytes().await?)?;
                                if identity["nonce"] == nonce && identity["home"] == home.to_string_lossy().as_ref() && identity["product"] == "Luna" && identity["version"] == expected_version["version"] {
                                    return Ok(reqwest::Url::parse(&format!("{base}/"))?)
                                }
                                bail!("The dashboard identity did not match this installation")
                            }
                        }
                    }
                }
            }
            tokio::time::sleep(Duration::from_millis(150)).await;
        }
    }.await;
    let _ = fs::remove_file(&ready);
    match outcome {
        Ok(url) => {
            let origin = url.origin();
            // Separate label: dashboard never inherits the bundled bootstrap's native ACL.
            let window = tauri::WebviewWindowBuilder::new(&app, "dashboard", tauri::WebviewUrl::External(url))
                .title("Luna").inner_size(1200.0, 820.0).min_inner_size(720.0, 520.0)
                .background_color(tauri::window::Color(23, 19, 43, 255))
                .visible(!state.hidden_launch.load(Ordering::Relaxed))
                .on_navigation(move |url| {
                    if url.origin() == origin { return true }
                    if matches!(url.scheme(), "https" | "http") { let _ = tauri_plugin_opener::open_url(url.as_str(), None::<&str>); }
                    false
                })
                .on_new_window(|url, _| {
                    // OAuth uses window.open; keep login in the system browser.
                    if matches!(url.scheme(), "https" | "http") {
                        let _ = tauri_plugin_opener::open_url(url.as_str(), None::<&str>);
                    }
                    tauri::webview::NewWindowResponse::Deny
                }).build();
            match window {
                Ok(window) => {
                    *state.session.lock().await = Some(controls::DashboardSession { url: window.url()?, token });
                    *state.backend.lock().await = Some(child);
                    let _ = app.emit("luna-dashboard-ready", ());
                    if let Some(main) = app.get_webview_window("main") { main.hide()?; }
                    controls::refresh_menus(&app)?;
                    if state.preferences.lock().unwrap().start_companion {
                        let app = app.clone();
                        tauri::async_runtime::spawn(async move {
                            if let Err(error) = controls::companion(&app, "start").await { controls::show_settings(&app); let _ = app.emit("luna-controls-error", error.to_string()); }
                        });
                    }
                    Ok(())
                },
                Err(e) => { stop(&mut child).await; Err(e.into()) },
            }
        },
        Err(e) => { stop(&mut child).await; Err(e) },
    }
}

#[tauri::command]
async fn luna_start(app: tauri::AppHandle, window: tauri::WebviewWindow, state: tauri::State<'_, Arc<State>>, repair: Option<bool>) -> Result<(), String> {
    require_bootstrap(&window)?;
    let result = start(app.clone(), &state, repair.unwrap_or(false)).await;
    if result.is_err() { controls::show_settings(&app); }
    result.map_err(|e| e.to_string())
}
#[tauri::command]
fn luna_cancel(window: tauri::WebviewWindow, state: tauri::State<'_, Arc<State>>) -> Result<(), String> {
    require_bootstrap(&window)?;
    state.cancelled.store(true, Ordering::Relaxed); Ok(())
}
#[tauri::command]
fn luna_status(window: tauri::WebviewWindow) -> Result<serde_json::Value, String> {
    require_bootstrap(&window)?;
    let root = home().map_err(|e| e.to_string())?;
    let selected = selected(&root).ok().flatten();
    let current = selected.as_ref().and_then(|p| fs::read(p.join("luna-release.json")).ok()).and_then(|bytes| serde_json::from_slice::<serde_json::Value>(&bytes).ok());
    let available = option_env!("LUNA_RELEASE_DESCRIPTOR_JSON").and_then(|s| serde_json::from_str::<serde_json::Value>(s).ok());
    let version = current.as_ref().and_then(|v| v["version"].as_str());
    let next = available.as_ref().and_then(|v| v["version"].as_str());
    Ok(serde_json::json!({"installed": selected.is_some(), "version": version, "available": next,
        "update_available": version.and_then(|v| semver::Version::parse(v).ok()).zip(next.and_then(|v| semver::Version::parse(v).ok())).map(|(old, new)| new > old).unwrap_or(false),
        "force_setup": std::env::args().any(|arg| arg == "--repair"),
        "background_launch": std::env::args().any(|arg| arg == "--background")}))
}

#[tauri::command]
fn luna_desktop_preferences(app: tauri::AppHandle, window: tauri::WebviewWindow) -> Result<serde_json::Value, String> {
    require_bootstrap(&window)?;
    controls::status(&app).map_err(|error| error.to_string())
}

#[tauri::command]
fn luna_set_desktop_preferences(app: tauri::AppHandle, window: tauri::WebviewWindow, patch: controls::Patch) -> Result<serde_json::Value, String> {
    require_bootstrap(&window)?;
    controls::update(&app, patch).map_err(|error| error.to_string())
}

#[tauri::command]
async fn luna_companion(app: tauri::AppHandle, window: tauri::WebviewWindow, action: String) -> Result<(), String> {
    require_bootstrap(&window)?;
    controls::companion(&app, &action).await.map_err(|error| error.to_string())
}

#[tauri::command]
fn luna_open(app: tauri::AppHandle, window: tauri::WebviewWindow) -> Result<(), String> {
    require_bootstrap(&window)?;
    controls::show(&app);
    Ok(())
}

#[tauri::command]
fn luna_quit(app: tauri::AppHandle, window: tauri::WebviewWindow) -> Result<(), String> {
    require_bootstrap(&window)?;
    controls::quit(&app);
    Ok(())
}

#[tauri::command]
async fn luna_desktop_appearance(app: tauri::AppHandle, window: tauri::WebviewWindow) -> Result<serde_json::Value, String> {
    require_bootstrap(&window)?;
    controls::appearance(&app).await.map_err(|error| error.to_string())
}

#[tauri::command]
fn luna_window_appearance(app: tauri::AppHandle, window: tauri::WebviewWindow, dark: bool) -> Result<(), String> {
    require_bootstrap(&window)?;
    app.set_theme(Some(if dark { tauri::Theme::Dark } else { tauri::Theme::Light }));
    Ok(())
}

fn require_bootstrap(window: &tauri::WebviewWindow) -> Result<(), String> {
    let url = window.url().map_err(|e| e.to_string())?;
    if window.label() != "main" || !bootstrap_origin(&url) { return Err("Native setup controls are only available in Luna's bundled installer".into()) }
    Ok(())
}
fn bootstrap_origin(url: &reqwest::Url) -> bool {
    (url.scheme() == "tauri" && url.host_str() == Some("localhost")) ||
        (matches!(url.scheme(), "http" | "https") && url.host_str() == Some("tauri.localhost")) ||
        (cfg!(debug_assertions) && url.scheme() == "http" && url.host_str() == Some("127.0.0.1") && url.port() == Some(5175))
}

pub fn run() {
    #[cfg(target_os = "linux")]
    if let Err(error) = appimage_menu::register_current() {
        eprintln!("Luna could not add its application menu entry: {error}");
    }
    let home = home().expect("Cannot locate Luna's data directory");
    fs::create_dir_all(&home).expect("Cannot create Luna's data directory");
    #[cfg(unix)] { use std::os::unix::fs::PermissionsExt; fs::set_permissions(&home, fs::Permissions::from_mode(0o700)).expect("Cannot protect Luna's home"); }
    fs::write(home.join(".desktop-installation.json"), "{\"product\":\"Luna\",\"format\":1}").expect("Cannot mark Luna's desktop home");
    let preferences = controls::load(&home).expect("Cannot read Luna's launcher preferences");
    let state = Arc::new(State { busy: Mutex::new(()), cancelled: AtomicBool::new(false), backend: Mutex::new(None),
        home: home.clone(), preferences: std::sync::Mutex::new(preferences), tray_available: AtomicBool::new(false),
        hidden_launch: AtomicBool::new(false), session: Mutex::new(None), companion_control: Mutex::new(()) });
    let cleanup = state.clone();
    tauri::Builder::default().manage(state)
        .plugin(tauri_plugin_single_instance::init(|app, arguments, _| {
            if !arguments.iter().any(|arg| arg == "--background") { controls::show(app); }
        }))
        .plugin(tauri_plugin_autostart::Builder::new().app_name("Luna")
            .args(["--background".to_owned(), "--luna-home".to_owned(), home.to_string_lossy().into_owned()]).build())
        .plugin(tauri_plugin_dialog::init())
        .on_menu_event(|app, event| {
            if controls::handle_menu(app, event.id().as_ref()) { return }
            if event.id().as_ref() == "luna-quit" {
                controls::quit(app);
            }
            if event.id().as_ref() == "luna-repair" {
                let state = app.state::<Arc<State>>().inner().clone(); let app = app.clone();
                tauri::async_runtime::spawn(async move {
                    if let Some(mut child) = state.backend.lock().await.take() { stop(&mut child).await; }
                    state.session.lock().await.take();
                    if let Some(dashboard) = app.get_webview_window("dashboard") { let _ = dashboard.destroy(); }
                    if let Some(main) = app.get_webview_window("main") { let _ = main.show(); let _ = main.set_focus(); }
                    let _ = app.emit("luna-repair-requested", ());
                });
            }
        })
        .invoke_handler(tauri::generate_handler![luna_start, luna_cancel, luna_status, luna_desktop_preferences, luna_set_desktop_preferences, luna_companion, luna_open, luna_quit, luna_desktop_appearance, luna_window_appearance])
        .setup(|app| {
            let root = app.state::<Arc<State>>().home.clone();
            let lock = fs::OpenOptions::new().create(true).read(true).write(true).open(root.join(".desktop.lock"))?;
            lock.try_lock_exclusive()?;
            app.manage(DesktopLock { _handle: lock });
            controls::setup(app.handle())?;
            let app = app.handle().clone(); let state = app.state::<Arc<State>>().inner().clone();
            tauri::async_runtime::spawn(async move {
                loop {
                    tokio::time::sleep(Duration::from_secs(1)).await;
                    let lost = {
                        let mut backend = state.backend.lock().await;
                        if backend.as_mut().and_then(|child| child.try_wait().ok().flatten()).is_some() { backend.take(); true } else { false }
                    };
                    if lost {
                        state.session.lock().await.take();
                        if let Some(dashboard) = app.get_webview_window("dashboard") { let _ = dashboard.destroy(); }
                        if let Some(main) = app.get_webview_window("main") { let _ = main.show(); let _ = main.set_focus(); }
                        let _ = app.emit("luna-backend-lost", ());
                    }
                }
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                let state = window.state::<Arc<State>>();
                if state.preferences.lock().unwrap().keep_in_background && state.tray_available.load(Ordering::Relaxed)
                    && state.backend.try_lock().map(|backend| backend.is_some()).unwrap_or(false) {
                    api.prevent_close(); let _ = window.hide(); return
                }
                state.cancelled.store(true, Ordering::Relaxed);
                if state.busy.try_lock().is_err() {
                    api.prevent_close();
                    let state = state.inner().clone();
                    let app = window.app_handle().clone();
                    tauri::async_runtime::spawn(async move { let _done = state.busy.lock().await; app.exit(0); });
                } else { window.app_handle().exit(0); }
            }
        })
        .build(tauri::generate_context!()).expect("Cannot start Luna's window")
        .run(move |_, event| if matches!(event, tauri::RunEvent::Exit) {
            cleanup.cancelled.store(true, Ordering::Relaxed);
            tauri::async_runtime::block_on(async { if let Some(mut child) = cleanup.backend.lock().await.take() { stop(&mut child).await; } });
        });
}

#[cfg(test)]
mod tests {
    use super::*;
    struct Scratch(PathBuf);
    impl Scratch {
        fn new() -> Self { let path = std::env::temp_dir().join(format!("luna-launcher-test-{}", uuid::Uuid::new_v4())); fs::create_dir(&path).unwrap(); Self(path) }
    }
    impl Drop for Scratch { fn drop(&mut self) { let _ = fs::remove_dir_all(&self.0); } }

    #[tokio::test]
    async fn cancellation_interrupts_a_stalled_network_operation() {
        let cancelled = Arc::new(AtomicBool::new(false));
        let trigger = cancelled.clone();
        tokio::spawn(async move { tokio::time::sleep(Duration::from_millis(20)).await; trigger.store(true, Ordering::Relaxed); });
        let result = tokio::time::timeout(Duration::from_secs(1), cancellable(&cancelled, std::future::pending::<()>())).await;
        assert!(result.unwrap().unwrap_err().to_string().contains("cancelled"));
        assert_eq!(cancellable(&AtomicBool::new(false), async { 42 }).await.unwrap(), 42);
    }
    #[test]
    fn managed_python_children_use_utf8_on_every_platform() {
        let cmd = command(Path::new("python"), Path::new("home"));
        let vars: std::collections::HashMap<_, _> = cmd.as_std().get_envs().collect();
        assert_eq!(vars.get(std::ffi::OsStr::new("PYTHONUTF8")), Some(&Some(std::ffi::OsStr::new("1"))));
    }
    #[test]
    fn a_legacy_home_is_preserved_and_a_clean_sibling_is_chosen() {
        let temp = Scratch::new(); let base = temp.0.join(".luna"); fs::create_dir(&base).unwrap();
        fs::write(base.join("SOUL.md"), "legacy character").unwrap();
        assert_eq!(clean_home(base.clone()), temp.0.join(".luna-desktop"));
        assert_eq!(fs::read_to_string(base.join("SOUL.md")).unwrap(), "legacy character");
    }
    #[test]
    fn an_owned_interrupted_install_keeps_the_same_home_on_retry() {
        let temp = Scratch::new(); let base = temp.0.join(".luna"); fs::create_dir(&base).unwrap();
        fs::write(base.join(".desktop-installation.json"), "{}").unwrap();
        fs::write(base.join("config.yaml"), "settings").unwrap();
        assert_eq!(clean_home(base.clone()), base);
    }
    #[test]
    fn pointers_cannot_select_an_unverified_or_external_directory() {
        let temp = Scratch::new(); let home = temp.0.join("home"); fs::create_dir_all(home.join("releases/one")).unwrap();
        fs::write(home.join("current-release.json"), r#"{"path":"releases/one"}"#).unwrap();
        assert!(selected(&home).is_err());
        fs::write(home.join("releases/one/.ready"), "verified").unwrap();
        assert_eq!(selected(&home).unwrap().unwrap(), home.join("releases/one").canonicalize().unwrap());
        fs::write(temp.0.join(".ready"), "verified").unwrap();
        fs::write(home.join("current-release.json"), r#"{"path":".."}"#).unwrap();
        assert!(selected(&home).is_err());
    }
    #[test]
    fn archives_cannot_create_symlinks() {
        let temp = Scratch::new(); let archive = temp.0.join("bad.tar.gz");
        let gzip = flate2::write::GzEncoder::new(fs::File::create(&archive).unwrap(), flate2::Compression::default());
        let mut tar = tar::Builder::new(gzip); let mut header = tar::Header::new_gnu();
        header.set_entry_type(tar::EntryType::Symlink); header.set_size(0); header.set_mode(0o777);
        tar.append_link(&mut header, "release/link", "../../outside").unwrap();
        tar.into_inner().unwrap().finish().unwrap();
        assert!(unpack(&archive, &temp.0.join("out"), false).is_err());
        assert!(!temp.0.join("outside").exists());
    }
    #[test]
    fn dashboard_and_external_origins_never_gain_setup_authority() {
        assert!(bootstrap_origin(&reqwest::Url::parse("tauri://localhost/index.html").unwrap()));
        assert!(bootstrap_origin(&reqwest::Url::parse("https://tauri.localhost/index.html").unwrap()));
        for url in ["http://127.0.0.1:9119/onboarding", "https://example.com", "https://tauri.localhost.example.com", "file:///tmp/index.html"] {
            assert!(!bootstrap_origin(&reqwest::Url::parse(url).unwrap()));
        }
    }
    #[test]
    #[ignore = "requires the actual prebuilt release artifact via LUNA_TEST_ARCHIVE"]
    fn extracts_the_actual_release_archive() {
        let temp = Scratch::new(); let archive = PathBuf::from(std::env::var_os("LUNA_TEST_ARCHIVE").expect("LUNA_TEST_ARCHIVE is required"));
        unpack(&archive, &temp.0.join("release"), false).unwrap();
        for name in ["luna-release.json", ".luna-assemble-manifest.json", "hermes_cli/web_dist/index.html", "luna/deploy/desktop_install.py"] {
            assert!(temp.0.join("release").join(name).is_file(), "missing {name}");
        }
    }
}
