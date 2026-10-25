# plugin-catalog — empty by product decision

Luna ships the plugin catalog **empty and offline** (PRODUCT_PLAN §4). There is no live
fetch, no cached catalog document, and no bundled third-party entries: the engine's
`hermes plugins catalog` / dashboard plugin hub resolve this directory only.

`removed.yaml` is the install kill-list (name or repo match). It is kept as the single
blocklist surface — entries here are refused at install even if a catalog returns later.

If a curated catalog is ever productized again, entries are single `*.yaml` files in this
directory (one plugin each, exact 40-hex commit SHA pins) and the loader in
`hermes_cli/plugin_catalog.py` already validates them. Keep the offline policy unless the
product deliberately ships a networked catalog with its own review process.
