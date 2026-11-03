# Updates

New versions of Smartify Kombi are installed from the dashboard: **Settings → Updates**.
The van and the remote dashboard each have this card and update themselves.

## Your choice

| Setting | What happens |
|---|---|
| **Off** | No checks. You can still press **Check now**. |
| **Tell me** (default) | A phone notification when a new version is out ([notifications](notifications.md) must be set up). You choose when to install it. |
| **Automatic** | The notification, and the van installs it at night (3:00–5:00) while parked. A failed update is not retried by itself. |

The remote dashboard shows new versions in its own Settings. Its **Automatic** setting
works only on hosting that can finish work in the background (most PHP-FPM and
LiteSpeed hosting can). Otherwise the card says so, and you install with one tap.

## Installing and going back

**Update to …** shows what is new first (the changelog). To go back, open
**All versions and going back** and pick an earlier version. Your settings and data
stay either way.

Versions before 0.4.0 are not listed, because they can't update themselves.

## What makes it safe

- **Only official releases.** The van installs only release tags of the project. The
  prebuilt dashboard is checked against the release's `SHA256SUMS`. A download that
  doesn't match changes nothing.
- **Backup first.** The van copies its database to `backend/data/backups/` before
  changing anything (the last 5 are kept). The remote dashboard keeps its previous files
  in `private/backups/`.
- **Automatic undo.** If the new version doesn't start, the previous code, dashboard and
  database are put back, and you get a notification saying what went wrong.
- **No root.** The updater (`deploy/updater.py`) runs as your normal user. The only
  extra right it has is restarting Smartify.

During a van update, the dashboard is offline for about a minute (longer on a Pi 3 when
Python packages change). As with any restart of Smartify, the relays are switched off
while it restarts. That's why automatic updates wait for the night.

## When the dashboard says it can't install

- **"run the installer once more"**: the updater isn't set up yet (installs from before
  0.4.0). On the Pi: `cd ~/smartify-kombi && sudo ./deploy/install.sh`
- **"a developer copy"**: the Smartify folder has code changes, or is newer than the
  newest release. Update it with git, or from the terminal: `sudo ./deploy/update.sh`
- **Remote dashboard: "not writable" / "zip extension"**: update by uploading
  `installer.php` from the newest release, as described in [cloud/README.md](../cloud/README.md).

Logs of the last van update: `journalctl -u smartify-update`.
