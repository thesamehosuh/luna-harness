//! Native lifecycle controls. Dashboard pages never receive these permissions.
use super::*;
use tauri::menu::{CheckMenuItem, IsMenuItem, Menu, MenuItem, MenuItemKind, PredefinedMenuItem};
#[cfg(target_os = "macos")]
use tauri::menu::Submenu;
use tauri_plugin_dialog::DialogExt;

#[derive(Clone, Default, Deserialize, Serialize)]
#[serde(default)]
pub(super) struct Preferences {
    pub keep_in_background: bool,
    pub start_companion: bool,
}

#[derive(Default, Deserialize)]
pub(super) struct Patch {
    launch_at_login: Option<bool>,
    keep_in_background: Option<bool>,
    start_companion: Option<bool>,
}

#[derive(Clone)]
pub(super) struct DashboardSession { pub url: reqwest::Url, pub token: String }

pub(super) async fn appearance(app: &tauri::AppHandle) -> Result<serde_json::Value> {
    let state = app.state::<Arc<State>>();
    let path = state.home.join(".desktop-appearance.json");
    let session = state.session.lock().await.clone();
    if let Some(session) = session {
        let client = reqwest::Client::builder().no_proxy().timeout(Duration::from_secs(5)).build()?;
        let get = |endpoint: &'static str| {
            let client = client.clone(); let session = session.clone();
            async move {
                let response = client.get(session.url.join(endpoint)?).bearer_auth(session.token).send().await?.error_for_status()?;
                let bytes = response.bytes().await?;
                if bytes.len() > 4 * 1024 * 1024 { bail!("Theme response exceeds the launcher limit") }
                Ok::<serde_json::Value, anyhow::Error>(serde_json::from_slice(&bytes)?)
            }
        };
        if let Ok((themes, font)) = tokio::try_join!(get("api/dashboard/themes"), get("api/dashboard/font")) {
            let report = serde_json::json!({"themes": themes, "font": font["font"]});
            let bytes = serde_json::to_vec(&report)?;
            if fs::read(&path).ok().as_deref() != Some(&bytes) {
                let temporary = path.with_extension(format!("{}.tmp", uuid::Uuid::new_v4()));
                fs::write(&temporary, &bytes)?;
                #[cfg(unix)] { use std::os::unix::fs::PermissionsExt; fs::set_permissions(&temporary, fs::Permissions::from_mode(0o600))?; }
                fs::rename(&temporary, &path)?;
            }
            return Ok(report)
        }
    }
    if let Ok(metadata) = fs::metadata(&path) {
        if metadata.len() <= 4 * 1024 * 1024 {
            if let Ok(value) = serde_json::from_slice::<serde_json::Value>(&fs::read(path)?) { return Ok(value) }
        }
    }
    Ok(serde_json::json!({"themes": {"active": "sakura-dusk", "themes": []}, "font": "theme"}))
}

#[cfg(target_os = "linux")]
fn startup_path() -> Result<PathBuf> {
    Ok(dirs::config_dir().context("Cannot locate your desktop configuration directory")?.join("autostart/org.luna.companion.desktop"))
}

#[cfg(target_os = "linux")]
fn quote_exec(value: &str) -> Result<String> {
    if value.chars().any(char::is_control) { bail!("Launch at login cannot use a path containing control characters") }
    let mut argument = String::from("\"");
    for character in value.chars() {
        if matches!(character, '\\' | '"' | '$' | '`') { argument.push('\\'); }
        if character == '%' { argument.push('%'); }
        argument.push(character);
    }
    argument.push('"');
    // Desktop-entry string escapes are processed before Exec argument quoting.
    Ok(argument.replace('\\', "\\\\"))
}

#[cfg(target_os = "linux")]
fn startup_executable(current: PathBuf, directory: Option<std::ffi::OsString>, image: Option<std::ffi::OsString>) -> PathBuf {
    // Parent apps (including AppImage-based editors) export their own APPIMAGE
    // variables to children. Only register an image that actually contains us.
    match (directory.map(PathBuf::from), image.map(PathBuf::from)) {
        (Some(directory), Some(image)) if current.starts_with(&directory) && image.is_file() => image,
        _ => current,
    }
}

fn startup_enabled(app: &tauri::AppHandle) -> Result<bool> {
    #[cfg(target_os = "linux")] {
        let _ = app;
        match fs::read_to_string(startup_path()?) {
            Ok(text) => Ok(!text.lines().any(|line| matches!(line.trim(), "Hidden=true" | "X-GNOME-Autostart-enabled=false"))),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
            Err(error) => Err(error.into()),
        }
    }
    #[cfg(not(target_os = "linux"))] {
        Ok(app.try_state::<tauri_plugin_autostart::AutoLaunchManager>().context("Startup controls are preparing")?.is_enabled()?)
    }
}

fn set_startup(app: &tauri::AppHandle, enabled: bool) -> Result<()> {
    #[cfg(target_os = "linux")] {
        let path = startup_path()?;
        if !enabled { match fs::remove_file(path) { Ok(()) => (), Err(error) if error.kind() == std::io::ErrorKind::NotFound => (), Err(error) => return Err(error.into()) }; return Ok(()) }
        let executable = startup_executable(std::env::current_exe()?, std::env::var_os("APPDIR"), app.env().appimage);
        let executable = executable.to_str().context("The launcher path cannot be encoded for desktop startup")?;
        if executable.contains('=') { bail!("The launcher path contains '=' and cannot be used by desktop startup") }
        let root = app.state::<Arc<State>>().home.clone();
        let root = root.to_str().context("The Luna home cannot be encoded for desktop startup")?;
        let command = [executable, "--background", "--luna-home", root].into_iter().map(quote_exec).collect::<Result<Vec<_>>>()?.join(" ");
        fs::create_dir_all(path.parent().unwrap())?;
        let temporary = path.with_extension(format!("{}.tmp", uuid::Uuid::new_v4()));
        let result = (|| -> Result<()> {
            fs::write(&temporary, format!("[Desktop Entry]\nType=Application\nName=Luna\nExec={command}\nTerminal=false\nStartupNotify=false\n"))?;
            fs::rename(&temporary, path)?; Ok(())
        })();
        let _ = fs::remove_file(temporary); result
    }
    #[cfg(not(target_os = "linux"))] {
        let startup = app.try_state::<tauri_plugin_autostart::AutoLaunchManager>().context("Startup controls are preparing")?;
        if enabled { startup.enable()? } else { startup.disable()? }; Ok(())
    }
}

pub(super) fn load(root: &Path) -> Result<Preferences> {
    match fs::read(root.join(".desktop-preferences.json")) {
        Ok(bytes) => Ok(serde_json::from_slice(&bytes)?),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(Preferences::default()),
        Err(e) => Err(e.into()),
    }
}

fn save(root: &Path, preferences: &Preferences) -> Result<()> {
    let temporary = root.join(format!(".desktop-preferences-{}", uuid::Uuid::new_v4()));
    let result = (|| -> Result<()> {
        let mut options = fs::OpenOptions::new(); options.write(true).create_new(true);
        #[cfg(unix)] { use std::os::unix::fs::OpenOptionsExt; options.mode(0o600); }
        let mut file = options.open(&temporary)?;
        file.write_all(&serde_json::to_vec(preferences)?)?; file.sync_all()?;
        fs::rename(&temporary, root.join(".desktop-preferences.json"))?;
        Ok(())
    })();
    let _ = fs::remove_file(temporary);
    result
}

pub(super) fn status(app: &tauri::AppHandle) -> Result<serde_json::Value> {
    let state = app.state::<Arc<State>>();
    let prefs = state.preferences.lock().map_err(|_| anyhow::anyhow!("Launcher settings are busy"))?.clone();
    let startup = startup_enabled(app);
    Ok(serde_json::json!({"launch_at_login": startup.as_ref().ok(), "startup_error": startup.err().map(|e| e.to_string()),
        "keep_in_background": prefs.keep_in_background, "start_companion": prefs.start_companion,
        "tray_available": state.tray_available.load(Ordering::Relaxed), "installed": selected(&state.home)?.is_some()}))
}

pub(super) fn update(app: &tauri::AppHandle, patch: Patch) -> Result<serde_json::Value> {
    let state = app.state::<Arc<State>>();
    if patch.launch_at_login == Some(true) && selected(&state.home)?.is_none() { bail!("Install Luna before enabling launch at login") }
    if patch.keep_in_background == Some(true) && !state.tray_available.load(Ordering::Relaxed) { bail!("This desktop has no available tray. Closing the window will quit Luna.") }
    {
        let mut prefs = state.preferences.lock().map_err(|_| anyhow::anyhow!("Launcher settings are busy"))?;
        let mut next = prefs.clone();
        if let Some(value) = patch.keep_in_background { next.keep_in_background = value; }
        if let Some(value) = patch.start_companion { next.start_companion = value; }
        let previous_startup = if patch.launch_at_login.is_some() { Some(startup_enabled(app)?) } else { None };
        if let Some(value) = patch.launch_at_login { set_startup(app, value)?; }
        if let Err(error) = save(&state.home, &next) {
            if let Some(value) = previous_startup { let _ = set_startup(app, value); }
            return Err(error);
        }
        *prefs = next;
    }
    refresh_menus(app)?;
    let report = status(app)?;
    let _ = app.emit("luna-preferences-changed", &report);
    Ok(report)
}

fn items(app: &tauri::AppHandle) -> tauri::Result<Vec<MenuItemKind<tauri::Wry>>> {
    let state = app.state::<Arc<State>>();
    let prefs = state.preferences.lock().unwrap().clone();
    let installed = selected(&state.home).ok().flatten().is_some();
    Ok(vec![
        MenuItem::with_id(app, "luna-open", "Open Luna", true, None::<&str>)?.kind(),
        MenuItem::with_id(app, "luna-settings", "Launcher settings…", true, None::<&str>)?.kind(),
        PredefinedMenuItem::separator(app)?.kind(),
        CheckMenuItem::with_id(app, "luna-login", "Launch Luna at login", installed, startup_enabled(app).unwrap_or(false), None::<&str>)?.kind(),
        CheckMenuItem::with_id(app, "luna-background", "Keep Luna running when its window closes", state.tray_available.load(Ordering::Relaxed), prefs.keep_in_background, None::<&str>)?.kind(),
        CheckMenuItem::with_id(app, "luna-auto-companion", "Start companion when Luna opens", installed, prefs.start_companion, None::<&str>)?.kind(),
        PredefinedMenuItem::separator(app)?.kind(),
        MenuItem::with_id(app, "luna-companion-start", "Start background companion", installed, None::<&str>)?.kind(),
        MenuItem::with_id(app, "luna-companion-stop", "Stop background companion", installed, None::<&str>)?.kind(),
        MenuItem::with_id(app, "luna-repair", "Repair runtime…", true, None::<&str>)?.kind(),
        MenuItem::with_id(app, "luna-quit", "Quit Luna", true, Some("CmdOrCtrl+Q"))?.kind(),
    ])
}

fn tray_menu(app: &tauri::AppHandle) -> tauri::Result<Menu<tauri::Wry>> {
    let owned = items(app)?;
    Menu::with_items(app, &owned.iter().map(|item| item as &dyn IsMenuItem<_>).collect::<Vec<_>>())
}

#[cfg(target_os = "macos")]
pub(super) fn menu(app: &tauri::AppHandle) -> tauri::Result<Menu<tauri::Wry>> {
    let owned = items(app)?;
    let luna = Submenu::with_items(app, "Luna", true, &owned.iter().map(|item| item as &dyn IsMenuItem<_>).collect::<Vec<_>>())?;
    let edit = Submenu::with_items(app, "Edit", true, &[
        &PredefinedMenuItem::undo(app, None)?, &PredefinedMenuItem::redo(app, None)?,
        &PredefinedMenuItem::cut(app, None)?, &PredefinedMenuItem::copy(app, None)?,
        &PredefinedMenuItem::paste(app, None)?, &PredefinedMenuItem::select_all(app, None)?,
    ])?;
    Menu::with_items(app, &[&luna, &edit])
}

pub(super) fn refresh_menus(app: &tauri::AppHandle) -> Result<()> {
    #[cfg(target_os = "macos")]
    app.set_menu(menu(app)?)?;
    if let Some(tray) = app.tray_by_id("luna") { tray.set_menu(Some(tray_menu(app)?))?; }
    Ok(())
}

pub(super) fn setup(app: &tauri::AppHandle) -> Result<()> {
    use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
    let state = app.state::<Arc<State>>();
    if let Some(icon) = app.default_window_icon() {
        let result = TrayIconBuilder::with_id("luna").icon(icon.clone()).tooltip("Luna").menu(&tray_menu(app)?)
            .show_menu_on_left_click(false)
            .on_tray_icon_event(|tray, event| {
                if matches!(event, TrayIconEvent::Click { button: MouseButton::Left, button_state: MouseButtonState::Up, .. }) { show(tray.app_handle()); }
            }).build(app);
        state.tray_available.store(result.is_ok(), Ordering::Relaxed);
    }
    refresh_menus(app)?;
    let hidden = std::env::args().any(|arg| arg == "--background") && state.tray_available.load(Ordering::Relaxed);
    state.hidden_launch.store(hidden, Ordering::Relaxed);
    if !hidden { show(app); }
    Ok(())
}

pub(super) fn show(app: &tauri::AppHandle) {
    app.state::<Arc<State>>().hidden_launch.store(false, Ordering::Relaxed);
    if let Some(window) = app.get_webview_window("dashboard").or_else(|| app.get_webview_window("main")) {
        let _ = window.unminimize(); let _ = window.show(); let _ = window.set_focus();
    }
}

pub(super) fn show_settings(app: &tauri::AppHandle) {
    app.state::<Arc<State>>().hidden_launch.store(false, Ordering::Relaxed);
    if let Some(window) = app.get_webview_window("main") { let _ = window.show(); let _ = window.set_focus(); }
}

pub(super) fn quit(app: &tauri::AppHandle) {
    let state = app.state::<Arc<State>>().inner().clone(); let app = app.clone();
    state.cancelled.store(true, Ordering::Relaxed);
    tauri::async_runtime::spawn(async move { let _done = state.busy.lock().await; app.exit(0); });
}

fn failure(app: &tauri::AppHandle, error: anyhow::Error) {
    app.dialog().message(error.to_string()).title("Luna").kind(tauri_plugin_dialog::MessageDialogKind::Error).show(|_| {});
}

pub(super) async fn companion(app: &tauri::AppHandle, verb: &str) -> Result<()> {
    let state = app.state::<Arc<State>>();
    let _operation = state.companion_control.try_lock().map_err(|_| anyhow::anyhow!("A companion action is already running"))?;
    let session = state.session.lock().await.clone().context("Open Luna before controlling its companion")?;
    change_companion(&session, verb, &state.cancelled).await
}

async fn change_companion(session: &DashboardSession, verb: &str, cancelled: &AtomicBool) -> Result<()> {
    if !matches!(verb, "start" | "stop") { bail!("Unknown companion action") }
    let client = reqwest::Client::builder().no_proxy().timeout(Duration::from_secs(15)).build()?;
    let response = client.post(session.url.join(&format!("api/gateway/{verb}"))?).bearer_auth(&session.token).send().await?;
    if !response.status().is_success() { bail!("The companion action could not start. Open System in the dashboard for details.") }
    let deadline = Instant::now() + Duration::from_secs(60);
    loop {
        if cancelled.load(Ordering::Relaxed) { bail!("The launcher is closing") }
        let response = client.get(session.url.join("api/status")?).bearer_auth(&session.token).send().await?;
        if response.status().is_success() {
            let status: serde_json::Value = serde_json::from_slice(&response.bytes().await?)?;
            if let Some(running) = status["gateway_running"].as_bool() {
                if running == (verb == "start") { return Ok(()) }
            }
        }
        if Instant::now() > deadline { bail!("The companion did not finish changing state. Open System to check its connection and logs.") }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
}

pub(super) fn handle_menu(app: &tauri::AppHandle, id: &str) -> bool {
    match id {
        "luna-open" => show(app),
        "luna-settings" => show_settings(app),
        "luna-login" | "luna-background" | "luna-auto-companion" => {
            let state = app.state::<Arc<State>>(); let prefs = state.preferences.lock().unwrap().clone();
            let patch = match id {
                "luna-login" => match startup_enabled(app) { Ok(value) => Patch { launch_at_login: Some(!value), ..Default::default() }, Err(e) => { failure(app, e); return true } },
                "luna-background" => Patch { keep_in_background: Some(!prefs.keep_in_background), ..Default::default() },
                _ => Patch { start_companion: Some(!prefs.start_companion), ..Default::default() },
            };
            if let Err(error) = update(app, patch) { let _ = refresh_menus(app); failure(app, error); }
        },
        "luna-companion-start" | "luna-companion-stop" => {
            let verb = if id == "luna-companion-start" { "start" } else { "stop" }; let app = app.clone();
            tauri::async_runtime::spawn(async move { if let Err(error) = companion(&app, verb).await { failure(&app, error); } });
        },
        _ => return false,
    }
    true
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn preferences_are_opt_in_and_survive_reopening() {
        let root = std::env::temp_dir().join(format!("luna-preferences-{}", uuid::Uuid::new_v4())); fs::create_dir(&root).unwrap();
        assert!(!load(&root).unwrap().keep_in_background);
        assert!(!load(&root).unwrap().start_companion);
        save(&root, &Preferences { keep_in_background: true, start_companion: true }).unwrap();
        assert!(load(&root).unwrap().keep_in_background && load(&root).unwrap().start_companion);
        #[cfg(unix)] { use std::os::unix::fs::PermissionsExt; assert_eq!(fs::metadata(root.join(".desktop-preferences.json")).unwrap().permissions().mode() & 0o777, 0o600); }
        fs::remove_dir_all(root).unwrap();
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn desktop_startup_quotes_spaces_and_literal_field_codes() {
        assert_eq!(quote_exec("Luna 100% complete").unwrap(), "\"Luna 100%% complete\"");
        assert!(quote_exec("Luna\nExec=other").is_err());
    }

    #[cfg(target_os = "linux")]
    #[test]
    fn a_parent_apps_appimage_is_never_registered_as_luna() {
        let root = std::env::temp_dir().join(format!("luna-startup-{}", uuid::Uuid::new_v4())); fs::create_dir(&root).unwrap();
        let image = root.join("Luna.AppImage"); fs::write(&image, "fixture").unwrap();
        let own = root.join("mounted/usr/bin/Luna");
        assert_eq!(startup_executable(own.clone(), Some(root.join("another-app").into_os_string()), Some(image.clone().into_os_string())), own);
        assert_eq!(startup_executable(root.join("mounted/usr/bin/Luna"), Some(root.join("mounted").into_os_string()), Some(image.clone().into_os_string())), image);
        fs::remove_dir_all(root).unwrap();
    }

    #[tokio::test]
    async fn companion_control_authenticates_and_waits_for_the_real_running_state() {
        use tokio::{io::{AsyncReadExt, AsyncWriteExt}, net::TcpListener};
        let server = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = server.local_addr().unwrap();
        let serving = tokio::spawn(async move {
            for (path, body) in [("POST /api/gateway/start", "{\"ok\":true}"), ("GET /api/status", "{\"gateway_running\":false}"), ("GET /api/status", "{\"gateway_running\":true}")] {
                let (mut connection, _) = server.accept().await.unwrap(); let mut request = Vec::new();
                loop { let mut bytes = [0; 1024]; let n = connection.read(&mut bytes).await.unwrap(); assert!(n > 0); request.extend_from_slice(&bytes[..n]); if request.windows(4).any(|part| part == b"\r\n\r\n") { break } }
                let request = String::from_utf8(request).unwrap();
                assert!(request.starts_with(path));
                assert!(request.to_ascii_lowercase().contains("authorization: bearer synthetic-test-token\r\n"));
                connection.write_all(format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: {}\r\n\r\n{body}", body.len()).as_bytes()).await.unwrap();
            }
        });
        let session = DashboardSession { url: format!("http://{address}/").parse().unwrap(), token: "synthetic-test-token".into() };
        change_companion(&session, "start", &AtomicBool::new(false)).await.unwrap();
        serving.await.unwrap();
        assert!(change_companion(&session, "other", &AtomicBool::new(false)).await.is_err());
    }
}
