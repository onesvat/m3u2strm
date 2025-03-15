# M3U2STRM

A Python utility that converts M3U playlists into STRM files for use with media servers like Jellyfin, Plex, or Kodi.

## What It Does

M3U2STRM takes your M3U playlist and:
1. Categorizes content into series, movies, and live TV
2. Creates STRM files that point to media streams
3. Organizes content in a folder structure compatible with media servers
4. Updates only when content changes
5. Sends notifications when new content is available

## Features

- ✅ Converts M3U streams to organized STRM files
- 📁 Categorizes content intelligently (series, movies, live TV)
- 📺 Creates proper TV series structure with seasons and episodes
- 🎬 Organizes movies with year information when available
- 📡 Generates a clean live.m3u file for direct use
- 🔄 Checks for content changes and updates efficiently
- 📱 Sends Telegram notifications for new content
- 🌐 Web UI for browsing and selecting content
- 🐳 Docker support for easy deployment
- 🔄 Optional Jellyfin library refresh integration

## Quick Start

### Using Docker (Recommended)

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/m3u2strm.git
cd m3u2strm

# 2. Edit docker-compose.yml with your settings

# 3. Run with Docker Compose
docker-compose up -d
```

### Manual Installation

```bash
# 1. Clone the repository
git clone https://github.com/yourusername/m3u2strm.git
cd m3u2strm

# 2. Install requirements
pip install -r requirements.txt

# 3. Run the application
python task.py
```

## Configuration

### Essential Settings

| Variable | Description | Example |
|----------|-------------|---------|
| `M3U_URL` | URL to download M3U playlist | `http://provider.com/playlist.m3u` |
| `M3U_FILE` | Path to local M3U file (alternative to URL) | `/path/to/playlist.m3u` |

### Content Groups
These settings define which M3U groups contain which type of content:

| Variable | Description | Example |
|----------|-------------|---------|
| `SERIES_GROUPS` | Groups containing TV series | `SERIES,DIZILER,TV_SHOWS` |
| `MOVIES_GROUPS` | Groups containing movies | `MOVIES,FILMLER,FILMS` |
| `LIVE_GROUPS` | Groups containing live TV | `LIVE,TV,CHANNELS` |

### Additional Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `TASK_INTERVAL` | Minutes between updates | `5` |
| `WEB_UI_PORT` | Port for the web interface | `8475` |
| `DEBUG_LOGGING` | Enable verbose logging | `false` |

### Notifications & Integration

| Variable | Description | Example |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Telegram bot API token | `123456789:ABCdefGhIjKlmnOpQrsTUVwxyz` |
| `TELEGRAM_CHAT_ID` | Telegram chat to receive notifications | `12345678` |
| `JELLYFIN_URL` | Jellyfin server URL | `http://192.168.1.100:8096` |
| `JELLYFIN_API_KEY` | Jellyfin API key | `32character_api_key_from_jellyfin` |

## Web UI

Access the web UI at `http://your-server-ip:8475` to:
- Browse all content from your M3U playlist
- Select specific series, movies, and channels to include
- Search for specific titles
- Save your selections for STRM generation

## How Content is Organized

```
vods/
├── series/
│   └── Show Name/
│       └── Season 01/
│           └── Show Name S01E01.strm
├── movies/
│   └── Movie Name (2023)/
│       └── Movie Name (2023).strm
└── live.m3u
```

## Content Detection Logic

- **Series**: Detected by patterns like "S01 E01" or "1x01" in titles
- **Movies**: Identified by group and optionally by year in parentheses
- **Live TV**: All streams in configured live groups

## M3U Format Example

```
#EXTM3U
#EXTINF:-1 tvg-id="series1" tvg-name="Breaking Bad S01 E01" group-title="SERIES",Breaking Bad S01 E01
http://example.com/series/breaking_bad_s01e01.mp4

#EXTINF:-1 tvg-id="movie1" tvg-name="Inception (2010)" group-title="MOVIES",Inception (2010)
http://example.com/movies/inception.mp4

#EXTINF:-1 tvg-id="live1" tvg-name="CNN" group-title="LIVE",CNN HD
http://example.com/live/cnn.m3u8
```

## Common Use Cases

1. **Adding IPTV to Jellyfin/Plex/Kodi**: Convert streams to structured libraries
2. **Organizing VOD Content**: Sort series and movies automatically
3. **Managing Live TV**: Create a single file for all channels
4. **Content Selection**: Use the web UI to pick which content to include

## Troubleshooting

- **No content appearing?** Check your group settings and filters in the web UI
- **Series not detected?** Ensure titles follow "S01 E01" or "1x01" naming patterns
- **Docker issues?** Verify volume mappings and environment variables

For more detailed examples and a sample M3U file, see `example.m3u` included in the repository.

## License

This project is licensed under the MIT License - see the LICENSE file for details.