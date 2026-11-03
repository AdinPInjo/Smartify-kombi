# Releasing a new version

Every release appears in **Settings → Updates** on every van and remote dashboard, with
its changelog. So a release is these steps:

1. **Write the changelog.** Add a section at the top of `CHANGELOG.md`:

   ```markdown
   ## 0.4.1 - 2026-11-20

   ### Fixed
   - What changed, written for the people using the van.
   ```

   Use `### Added`, `### Changed`, `### Fixed` or `### Note`, with `- ` items. A new
   feature raises the middle number (0.5.0), a fix raises the last one (0.4.1).

2. **Set the version** in all four files:
   `backend/pyproject.toml`, `backend/smartify/__init__.py`, `frontend/package.json`
   (and `package-lock.json`: `npm version 0.4.1 --no-git-tag-version`) and
   `cloud/api/lib.php` (`SMARTIFY_CLOUD_VERSION`). Check them with:

   ```bash
   python3 scripts/release_info.py check 0.4.1
   ```

3. **Commit, push, tag:**

   ```bash
   git commit -am "Release 0.4.1" && git push origin main
   git tag v0.4.1 && git push origin v0.4.1
   ```

The release workflow checks step 1 and 2 again (and stops if they don't match). It then
builds and publishes `dashboard.tar.gz`, `smartify-cloud.zip`, `installer.php`,
`versions.json` and `SHA256SUMS`. Vans see the new version within 6 hours, or straight
away with **Check now**.

## Rules that keep updates and going back safe

- **Database changes only add.** New tables and new columns are fine. Never rename or
  drop anything in a migration: an older version (after going back) must still work
  with the newer database. The same applies to `schema_sql()` in `cloud/api/lib.php`.
- **Never move or rename a released tag.** Vans install tags by name.
- **Changes to the system setup** (systemd units, polkit, packages from apt) are not
  applied by an update. Mention them in the changelog under `### Note` with the command
  to run (`sudo ./deploy/install.sh`).
