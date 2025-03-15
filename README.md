# M3U2STRM

A Python utility that converts M3U playlists into STRM files and folders for use with media servers like Jellyfin, Plex, or Kodi.

## Features

- Converts M3U playlist entries to organized STRM files
- Automatically categorizes content into series, movies, and live TV
- Properly structures TV series with seasons and episodes
- Creates movie folders with year information when available
- Deduplicates live TV channels (prioritizing higher quality versions)
- Generates a clean live.m3u file for direct use in media players
- Checks for content changes and only updates when necessary
- Sends Telegram notifications for new content
- Docker support for easy deployment

## Getting Started

### Prerequisites

- Python 3.9 or later
- Docker (optional, for containerized deployment)
- An M3U playlist file or URL
- Telegram bot (optional, for notifications)

### Installation

#### Using Docker (recommended)

1. Clone the repository:
```bash
git clone https://github.com/yourusername/m3u2strm.git
cd m3u2strm
```

2. Build the Docker image:
```bash
docker build -t m3u2strm:latest .
```

3. Run with Docker Compose:
```bash
docker-compose up -d
```

#### Manual Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/m3u2strm.git
cd m3u2strm
```

2. Install requirements:
```bash
pip install requests
```

3. Run the script:
```bash
python task.py
```

## Configuration

Configure the application using environment variables:

### Basic Configuration

- `M3U_FILE`: Path to local M3U file (if already downloaded)
- `M3U_URL`: URL to download M3U file from
- `TASK_INTERVAL`: Time between updates in minutes (default: 5)
- `DEBUG_LOGGING`: Set to "true" for verbose logging

### Content Categorization

- `SERIES_GROUPS`: Comma-separated list of group names for series content
- `MOVIES_GROUPS`: Comma-separated list of group names for movie content 
- `LIVE_GROUPS`: Comma-separated list of group names for live TV content
- `INCLUDE_SERIES`: Optional comma-separated list to filter specific series
- `INCLUDE_MOVIES`: Optional comma-separated list to filter specific series

### Telegram Notifications

- `TELEGRAM_BOT_TOKEN`: Your Telegram bot API token
- `TELEGRAM_CHAT_ID`: Telegram chat ID to receive notifications

### Docker Compose Example

```yaml
version: '3.8'

services:
  task-runner:
    image: m3u2strm:latest
    environment:
      - TASK_INTERVAL=30
      - M3U_URL=http://example.com/playlist.m3u
      - SERIES_GROUPS=SERIES,DIZILER
      - MOVIES_GROUPS=MOVIES,FILMLER
      - LIVE_GROUPS=LIVE,TV,ULUSAL
      - TELEGRAM_BOT_TOKEN=your_bot_token
      - TELEGRAM_CHAT_ID=your_chat_id
      - DEBUG_LOGGING=false
    volumes:
      - ./data:/app/vods
    restart: unless-stopped
```

## Output Structure

The converter creates the following structure:

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

## How It Works

1. The application parses the M3U file and categorizes items based on group titles
2. TV series are identified by patterns like "S01 E01" or "1x01" in the title
3. Movies are placed in folders with year information if available
4. Live TV channels are deduplicated, with preference for higher quality versions
5. STRM files contain direct URLs to the media sources
6. Changes are tracked with checksums to avoid unnecessary updates
7. When new content is detected, notifications are sent via Telegram (if configured)

## Notifications

When new content is added to your library:
- Detailed notifications are sent to your Telegram account
- The notification includes new series episodes and movies
- For series with multiple new episodes, they are grouped under the series name
- Live TV updates are also reported

## License

This project is licensed under the MIT License - see the LICENSE file for details.