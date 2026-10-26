# GTK3 security backport

Tauri’s Linux GTK3 dependency requires glib 0.18.5. The fixed 0.20 line targets a different GTK dependency family. This directory contains the original crates.io glib 0.18.5 source and its MIT license, with the two-line upstream fix for [GHSA-wrw7-89jp-8q8g](https://github.com/gtk-rs/gtk-rs-core/pull/1343): initialize a mutable output pointer and pass `&mut p` to `g_variant_get_child`.

Cargo uses this local copy through `[patch.crates-io]`. No external dependency or advisory is globally suppressed. Remove this copy when Tauri’s GTK3 line adopts the upstream fix.
