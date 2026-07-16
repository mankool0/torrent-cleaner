# Torrent Cleaner

Automatically clean up qBittorrent torrents by deleting those that meet configurable seeding criteria, with smart hardlink detection to preserve media library links. Optionally deletes torrents with dead trackers.

## Quick Start

```bash
cp .env.example .env
# Edit .env with your qBittorrent credentials and paths
docker-compose up -d
```

By default, runs in **dry run mode** — check logs with `docker-compose logs -f` to see what would be deleted before setting `DRY_RUN=false`.

## Configuration

Copy `.env.example` and configure:

| Variable | Default | Description |
|----------|---------|-------------|
| `QBITTORRENT_HOST` | *required* | qBittorrent host address |
| `QBITTORRENT_PORT` | `8080` | Web UI port |
| `QBITTORRENT_USERNAME` | *required* | Web UI username |
| `QBITTORRENT_PASSWORD` | *required* | Web UI password |
| `TORRENT_DIR` | `/data/torrents` | Torrent data path (inside container) |
| `MEDIA_LIBRARY_DIR` | `/data/media` | Media library path (inside container) |
| `PATH_ALIASES` | *(empty)* | Symlinks to bridge qBittorrent's paths into a single mount (see Volume Mounts) |
| `DATA_DIR` | `/app/data/torrent-cleaner` | Cache and logs directory |
| `DELETION_CRITERIA` | `30d 2.0` | Deletion rules (see below) |
| `DRY_RUN` | `true` | Set `false` to actually delete |
| `FIX_HARDLINKS` | `true` | Fix broken hardlinks before deleting |
| `MAX_DELETIONS_PER_RUN` | `10` | Safety cap on deletions per run (`0` = unlimited) |
| `ALLOW_EMPTY_MEDIA_LIBRARY` | `false` | Allow non-dry runs against an empty media library |
| `HARDLINK_BYTE_VERIFY` | `false` | Full byte comparison before replacing a file with a hardlink (extra I/O) |
| `MEDIA_EXTENSIONS` | `.mkv,.mp4,.avi,...` | Comma-separated media file extensions |
| `ENABLE_CACHE` | `true` | Cache file hashes in SQLite |
| `CACHE_DB_PATH` | `{DATA_DIR}/cache/file_cache.db` | Cache database path |
| `DELETE_DEAD_TRACKERS` | `false` | Delete torrents with dead trackers |
| `DEAD_TRACKER_MESSAGES` | *(empty)* | Pipe-separated tracker error messages |
| `DISCORD_WEBHOOK_URL` | *(empty)* | Discord webhook for notifications |
| `CRON_SCHEDULE` | `0 2 * * *` | Cron schedule (default: daily 2 AM) |
| `RUN_ON_STARTUP` | `false` | Run immediately on container start |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LOG_MAX_FILES` | `5` | Rotated log files to keep (`0` = keep all) |

### Volume Mounts

Update `docker-compose.yml` with your paths:

```yaml
services:
  torrent-cleaner:
    image: ghcr.io/mankool0/torrent-cleaner:latest
    volumes:
      - /path/to/torrents:/data/torrents       # read-write
      - /path/to/media:/data/media:ro          # read-only
      - cleaner-data:/app/data/torrent-cleaner # cache + logs
```

Two constraints must hold at the same time:

1. **Paths must match qBittorrent's namespace.** The cleaner operates on the save paths qBittorrent reports over the API, so those paths must resolve inside this container.
2. **Torrents and media must live under a single volume mount.** Hardlinks cannot cross separate bind mounts — the kernel returns `EXDEV` ("Invalid cross-device link") even when both mounts come from the same filesystem. Mounting `/path/to/torrents` and `/path/to/media` as two volumes breaks `FIX_HARDLINKS`.

The clean way to satisfy both is a single parent mount (as above) with qBittorrent using the same layout (`/data/torrents/...`). If your qBittorrent uses a different namespace (e.g. save paths under `/downloads`) and you can't change it, use `PATH_ALIASES` to create symlinks inside the single mount:

```yaml
    volumes:
      - /path/to/data:/data        # single mount containing torrents AND media
    environment:
      - PATH_ALIASES=/downloads=/data/torrents/downloads
      - TORRENT_DIR=/downloads
      - MEDIA_LIBRARY_DIR=/data/media
```

Format: comma-separated `link=target` pairs. qBittorrent's `/downloads/...` paths then resolve through the symlink into the single mount, so both deletion checks and hardlink fixing work.

### Safety Guards

A misconfigured mount or path mapping makes every torrent look unlinked — which, without protection, means mass deletion. Several guards protect against this:

- **Path visibility preflight**: if none of the torrent save paths reported by qBittorrent exist inside the container, the run aborts (warns in dry run).
- **Per-torrent file check**: a torrent whose files can't be inspected (missing/unreadable) is always kept, never deleted.
- **Empty media library**: if the media library index contains zero files, non-dry runs abort — set `ALLOW_EMPTY_MEDIA_LIBRARY=true` only if you really have no library.
- **Deletion cap**: at most `MAX_DELETIONS_PER_RUN` torrents are deleted per run (default 10, `0` = unlimited). Skipped deletions are reported in the summary and Discord notification and will proceed on subsequent runs.

### Deletion Criteria

`DELETION_CRITERIA` defines one or more rules. Rules are separated by `|` (OR logic). Within each rule, conditions are separated by spaces (AND logic). Duration uses `d`/`m`/`y` suffixes; ratio is a plain number.

```
# Single rule (default): delete when 30 days AND ratio >= 2.0
DELETION_CRITERIA=30d 2.0

# Multiple rules: (30d AND 2.0) OR (10d AND 0.5)
DELETION_CRITERIA=30d 2.0 | 10d 0.5

# Mixed: (30d AND 2.0) OR 90 days regardless of ratio
DELETION_CRITERIA=30d 2.0 | 90d

# Ratio only: delete when ratio >= 0.5
DELETION_CRITERIA=0.5
```

Even then, torrents are kept if their media files are hardlinked to the media library (or can be fixed). When multiple torrents share files via hardlinks, their stats are aggregated (max seeding time, summed ratio).

### Media Extensions

`MEDIA_EXTENSIONS` controls which file extensions count as "media" for keep/delete decisions. Only media files are considered when deciding whether a torrent's files are linked to the media library. Hardlink fixing still runs on **all** orphaned files regardless of extension.

```
# Default
MEDIA_EXTENSIONS=.mkv,.mp4,.avi,.mov,.m4v,.wmv,.flv,.webm,.ts,.m2ts
```

### Dead Tracker Cleanup

Disabled by default. When enabled, torrents are deleted (regardless of seeding criteria) if **all** real trackers report an error message matching one of your configured messages. DHT/PeX/LSD are ignored.

Note: unlike the criteria pass, dead-tracker deletion happens immediately — it skips the age/ratio rules, does not attempt hardlink fixing, and does not check whether files are linked. Files hardlinked into the media library are safe regardless (the library's copy survives), but a torrent whose content exists *only* in the torrent folder loses that content as soon as its trackers go dead — including downloads you haven't imported yet. Torrents whose files are not visible from the container are kept (see Safety Guards), and the `MAX_DELETIONS_PER_RUN` cap applies.

```
DELETE_DEAD_TRACKERS=true
DEAD_TRACKER_MESSAGES=Host not found (authoritative)|unregistered torrent
```

Messages are matched exactly, case-insensitive.

## Building Locally

```bash
docker-compose -f docker-compose.dev.yml up -d
```

## Testing

```bash
pip install -r requirements.txt -r tests/requirements-test.txt

# Unit tests (fast, no dependencies)
pytest tests/unit/ -v

# All tests (requires Docker for qBittorrent container)
pytest tests/ -v
```

## License

GPL-3.0 — see [LICENSE.txt](LICENSE.txt)
