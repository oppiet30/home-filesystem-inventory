# Home Filesystem Inventory

Read-only Python 3.11+ Linux filesystem inventory with SQLite, Git repository discovery, and ZIP/TAR archive inspection. The default scan root is the current user's home directory.

## Quick start

```bash
python3 -m unittest discover -s tests -v
python3 -m home_inventory scan
python3 -m home_inventory report repos
python3 -m home_inventory report largest
```

## Modes

- `quick` (default): file metadata and Git repository discovery.
- `normal`: additionally hash files matching previously seen sizes and list ZIP/TAR entries. Earlier candidates can remain unhashed.
- `deep`: hash regular files and archive entries. **Use only with trusted archives** until decompression limits are implemented.

Choose another root with `--root /home`. Data is stored in `~/.local/share/home-filesystem-inventory/inventory.db`. No files are deleted. Symbolic links and other filesystem devices are not traversed.

## Schedule with at

From the repository directory:

```bash
sudo systemctl enable --now atd
chmod +x scripts/run-scan.sh
echo "$PWD/scripts/run-scan.sh quick" | at now + 1 minute
tail -f ~/.local/state/home-filesystem-inventory/scan.log
```

The wrapper uses `flock` to prevent overlapping wrapper-launched scans. Do not run a separate direct scan against the same database concurrently.

## Reports

```bash
python3 -m home_inventory report repos
python3 -m home_inventory report largest
python3 -m home_inventory report duplicates
```

The duplicates report is preliminary and only includes already hashed files. Archive scanning does not currently support nested archives, RAR, or 7z.
