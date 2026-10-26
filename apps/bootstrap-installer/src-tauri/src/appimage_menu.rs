//! User-local menu integration for the portable Linux launcher.
//! Debian/RPM packages already install their own desktop entries.
use std::{fs, path::{Path, PathBuf}};

fn exec_path(path: &Path) -> std::io::Result<String> {
    let value = path.to_str().ok_or_else(|| std::io::Error::other("AppImage path must be UTF-8"))?;
    if value.contains(['\n', '\r']) { return Err(std::io::Error::other("Invalid AppImage path")); }
    let escaped = value.replace('\\', "\\\\\\\\").replace('"', "\\\\\"")
        .replace('`', "\\\\`").replace('$', "\\\\$").replace('%', "%%");
    Ok(format!("\"{escaped}\""))
}

pub fn register(source: &Path, data: &Path) -> std::io::Result<()> {
    use std::os::unix::fs::PermissionsExt;
    let directory = data.join("luna-launcher");
    fs::create_dir_all(&directory)?;
    let executable = directory.join("Luna.AppImage");
    if source != executable {
        // Publish atomically: a failed copy must not damage the previous launcher.
        let pending = directory.join(format!("Luna.AppImage.{}.pending", std::process::id()));
        fs::copy(source, &pending)?;
        fs::set_permissions(&pending, fs::Permissions::from_mode(0o755))?;
        fs::rename(pending, &executable)?;
    }
    let icon = directory.join("luna.png");
    fs::write(&icon, include_bytes!("../icons/128x128.png"))?;
    let applications = data.join("applications");
    fs::create_dir_all(&applications)?;
    let icon_value = icon.to_str().ok_or_else(|| std::io::Error::other("Icon path must be UTF-8"))?;
    if icon_value.contains(['\n', '\r']) { return Err(std::io::Error::other("Invalid icon path")); }
    let entry = format!("[Desktop Entry]\nType=Application\nName=Luna Harness\nComment=Your personal AI companion\nExec={}\nIcon={}\nTerminal=false\nCategories=Utility;\nStartupWMClass=Luna\n", exec_path(&executable)?, icon_value.replace('\\', "\\\\"));
    let pending = applications.join(format!("org.luna.companion.appimage.{}.pending", std::process::id()));
    fs::write(&pending, entry)?;
    fs::rename(pending, applications.join("org.luna.companion.appimage.desktop"))?;
    Ok(())
}

pub fn register_current() -> std::io::Result<()> {
    let Some(source) = std::env::var_os("APPIMAGE").map(PathBuf::from) else { return Ok(()) };
    let data = std::env::var_os("XDG_DATA_HOME").map(PathBuf::from).filter(|path| path.is_absolute())
        .or_else(|| std::env::var_os("HOME").map(|home| PathBuf::from(home).join(".local/share")))
        .ok_or_else(|| std::io::Error::other("Cannot locate application menu"))?;
    register(&source, &data)?;
    // Called before Tauri/plugin initialization: autostart must use the retained
    // launcher, rather than a download the user may move or delete.
    std::env::set_var("APPIMAGE", data.join("luna-launcher/Luna.AppImage"));
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn portable_launcher_survives_removing_download() {
        let root = std::env::temp_dir().join(format!("luna-menu-{}", std::process::id()));
        fs::create_dir_all(&root).unwrap();
        let source = root.join("download.AppImage"); fs::write(&source, "fixture executable").unwrap();
        let data = root.join("data with spaces");
        register(&source, &data).unwrap(); fs::remove_file(source).unwrap();
        assert_eq!(fs::read_to_string(data.join("luna-launcher/Luna.AppImage")).unwrap(), "fixture executable");
        let entry = fs::read_to_string(data.join("applications/org.luna.companion.appimage.desktop")).unwrap();
        assert!(entry.contains("Name=Luna Harness\n"));
        assert!(entry.contains("Exec=\"")); assert!(entry.contains("Terminal=false"));
        register(&data.join("luna-launcher/Luna.AppImage"), &data).unwrap();
        fs::remove_dir_all(root).unwrap();
    }
    #[test]
    fn desktop_exec_escapes_field_codes_and_metacharacters() {
        assert_eq!(exec_path(Path::new("/tmp/a%f $x.AppImage")).unwrap(), "\"/tmp/a%%f \\\\$x.AppImage\"");
        assert!(exec_path(Path::new("/tmp/a\nb")).is_err());
    }
}
