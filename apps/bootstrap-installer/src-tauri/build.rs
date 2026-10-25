fn main() {
    println!("cargo:rerun-if-env-changed=LUNA_RELEASE_DESCRIPTOR");
    if let Ok(path) = std::env::var("LUNA_RELEASE_DESCRIPTOR") {
        let data = std::fs::read_to_string(&path).expect("Cannot read Luna release descriptor");
        let value: serde_json::Value = serde_json::from_str(&data).expect("Invalid Luna release descriptor JSON");
        assert!(value["version"].is_string(), "Release version is required");
        assert!(value["runtime"]["url"].as_str().unwrap_or("").starts_with("https://"), "Release download must use HTTPS");
        assert_eq!(value["runtime"]["sha256"].as_str().unwrap_or("").len(), 64, "Release SHA-256 is required");
        println!("cargo:rerun-if-changed={path}");
        println!("cargo:rustc-env=LUNA_RELEASE_DESCRIPTOR_JSON={}", data.replace('\n', ""));
    } else if std::env::var("PROFILE").as_deref() == Ok("release") {
        panic!("Release launchers require LUNA_RELEASE_DESCRIPTOR; never ship an unpinned installer");
    }
    #[cfg(target_os = "windows")]
    let attributes = tauri_build::Attributes::new().windows_attributes(
        tauri_build::WindowsAttributes::new().app_manifest(include_str!("hermes-setup.manifest")));
    #[cfg(not(target_os = "windows"))]
    let attributes = tauri_build::Attributes::new();
    tauri_build::try_build(attributes).expect("Cannot build Luna's native window");
}
