import os
import time
import requests
import re
import shutil
from pathlib import Path
import hashlib
import json
import logging
import threading
import web_ui

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Enable debug logging with environment variable
if os.getenv("DEBUG_LOGGING", "false").lower() == "true":
    logger.setLevel(logging.DEBUG)

class M3UItem:
    def __init__(self, title, url, group_title, tvg_id="", tvg_name="", tvg_logo=""):
        self.title = title
        self.url = url
        self.group_title = group_title
        self.tvg_id = tvg_id
        self.tvg_name = tvg_name
        self.tvg_logo = tvg_logo


class SeriesItem(M3UItem):
    def __init__(self, title, url, group_title, season=None, episode=None, series_name=None, **kwargs):
        super().__init__(title, url, group_title, **kwargs)
        self.season = season
        self.episode = episode
        self.series_name = series_name


class MovieItem(M3UItem):
    def __init__(self, title, url, group_title, year=None, **kwargs):
        super().__init__(title, url, group_title, **kwargs)
        self.year = year


class LiveTVItem(M3UItem):
    def __init__(self, title, url, group_title, **kwargs):
        super().__init__(title, url, group_title, **kwargs)


def download_m3u_file(url, destination):
    response = requests.get(url)
    if response.status_code == 200:
        with open(destination, 'wb') as file:
            file.write(response.content)
        logger.info(f"Downloaded M3U file to {destination}")
        return True
    else:
        logger.error(f"Failed to download M3U file. Status code: {response.status_code}")
        return False


def parse_m3u_file(file_path):
    items = []
    
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()
    except UnicodeDecodeError:
        # Try with another encoding if UTF-8 fails
        with open(file_path, 'r', encoding='latin-1') as file:
            content = file.read()
    
    # Skip first line if it's #EXTM3U
    if content.strip().startswith('#EXTM3U'):
        content = content[content.find('#EXTM3U') + len('#EXTM3U'):]
    
    # Split by #EXTINF to get individual entries
    entries = content.split('#EXTINF:')[1:]
    
    for entry in entries:
        lines = entry.strip().split("\n", 1)
        if len(lines) < 2:
            continue
            
        info_line = lines[0]
        url = lines[1].strip()
        
        # Extract metadata from info line
        tvg_id = extract_attribute(info_line, 'tvg-id')
        tvg_name = extract_attribute(info_line, 'tvg-name')
        tvg_logo = extract_attribute(info_line, 'tvg-logo')
        group_title = extract_attribute(info_line, 'group-title')
        
        # Extract title (the part after the last comma in the info line)
        title_match = re.search(r',\s*([^,]+)$', info_line)
        title = title_match.group(1) if title_match else info_line
        
        items.append({
            'title': title,
            'url': url,
            'tvg_id': tvg_id,
            'tvg_name': tvg_name, 
            'tvg_logo': tvg_logo,
            'group_title': group_title
        })
        
    return items


def extract_attribute(text, attr_name):
    pattern = attr_name + '="([^"]*)"'
    match = re.search(pattern, text)
    return match.group(1) if match else ""



def categorize_items(items, all = False):
    """Categorize items based on filters only. No filters = no output."""
    # Load filters - these are now mandatory
    filters = web_ui.load_filters()

    series_filters = filters.get('series', [])
    movies_filters = filters.get('movies', [])
    live_filters = filters.get('live', [])
    series_groups_filters = os.getenv("SERIES_GROUPS", "").split(',')
    movies_groups_filters = os.getenv("MOVIES_GROUPS", "").split(',')
    live_groups_filters = os.getenv("LIVE_GROUPS", "").split(',')

    print(f"Series filters: {series_filters}")
    print(f"Movies filters: {movies_filters}")
    print(f"Live filters: {live_filters}")
    print(f"Series groups filters: {series_groups_filters}")
    print(f"Movies groups filters: {movies_groups_filters}")
    print(f"Live groups filters: {live_groups_filters}")
    
    series_items = []
    movie_items = []
    live_items = []
    
    # For live channels, we'll use a dictionary to track the best version of each channel
    channel_dict = {}
    
    for item in items:
        group = item.get('group_title', '')
        
        # Process TV series
        if series_filters or all:
            series_info = parse_series_info(item['title'])
            if series_info:
                # Check if this series is in our filter list and its group is in our group filters
                if ((series_info['series_name'].lower() in [s.lower() for s in series_filters] or all) and 
                    group in series_groups_filters):
                    series_item = SeriesItem(
                        title=item['title'],
                        url=item['url'],
                        group_title=group,
                        tvg_id=item['tvg_id'],
                        tvg_name=item['tvg_name'],
                        tvg_logo=item['tvg_logo'],
                        series_name=series_info['series_name'],
                        season=series_info['season'],
                        episode=series_info['episode']
                    )
                    series_items.append(series_item)
                    continue
        
        # Process movies
        if movies_filters or all:
            movie_title = item['title']

            # Check if this movie is in our filter list and its group is in our group filters
            if ((movie_title.lower() in [m.lower() for m in movies_filters] or all) and
                group in movies_groups_filters):
                movie_item = MovieItem(
                    title=item['title'],
                    url=item['url'],
                    group_title=group,
                    tvg_id=item['tvg_id'],
                    tvg_name=item['tvg_name'],
                    tvg_logo=item['tvg_logo'],
                )
                movie_items.append(movie_item)
                continue
        
        # Process live TV with both channel and group filters
        if live_filters or all:
            # Clean the title to remove quality indicators
            live_title = item['title']

            # Check if this live is in our filter list and its group is in our group filters
            if ((live_title.lower() in [l.lower() for l in live_filters] or all) and
                group in live_groups_filters):
        
                live_item = LiveTVItem(
                    title=item['title'],
                    url=item['url'],
                    group_title=group,
                    tvg_id=item['tvg_id'],
                    tvg_name=item['tvg_name'],
                    tvg_logo=item['tvg_logo']
                )
                
                live_items.append(live_item)
                continue


    
    return {
        'series': series_items,
        'movies': movie_items,
        'live': live_items
    }


def parse_series_info(title):
    # Pattern for "Series Name S01 E01" format
    pattern1 = r'(.*?)\s+S(\d+)\s+E(\d+)'
    # Pattern for "Series Name 1x01" format
    pattern2 = r'(.*?)\s+(\d+)x(\d+)'
    
    match = re.search(pattern1, title, re.IGNORECASE) or re.search(pattern2, title, re.IGNORECASE)
    
    if match:
        series_name = match.group(1).strip()
        season = int(match.group(2))
        episode = int(match.group(3))
        return {
            'series_name': series_name,
            'season': season,
            'episode': episode
        }
    return None


def extract_movie_year(title):
    # Look for a year in parentheses at the end of the title
    year_match = re.search(r'\((\d{4})\)$', title)
    if year_match:
        return year_match.group(1)
    return None


def sanitize_filename(name):
    """Remove invalid characters from filenames."""
    # Replace invalid characters for filenames with underscore
    invalid_chars = r'[<>:"/\\|?*]'
    sanitized = re.sub(invalid_chars, '_', name)
    # Remove trailing dots and spaces which are problematic on some filesystems
    sanitized = sanitized.rstrip('. ')
    return sanitized


def calculate_content_hash(content):
    """Calculate a hash for the given content."""
    if not content:
        logger.warning("Attempting to hash empty content")
        return "empty_content_hash"
    hash_value = hashlib.md5(content.encode('utf-8') if isinstance(content, str) else content).hexdigest()
    return hash_value


def normalize_path(path):
    """Normalize a path for consistent checksum keys."""
    # Convert to absolute path and normalize
    return os.path.normpath(path)


def load_checksums(checksums_file):
    """Load existing checksums from file."""
    if os.path.exists(checksums_file):
        try:
            with open(checksums_file, 'r') as f:
                checksums = json.load(f)
                logger.debug(f"Loaded {len(checksums)} checksums from {checksums_file}")
                
                # Debug: Print some sample checksums if available
                if checksums and logger.isEnabledFor(logging.DEBUG):
                    sample_keys = list(checksums.keys())[:3]
                    for key in sample_keys:
                        logger.debug(f"Sample checksum - Path: {key}, Hash: {checksums[key]}")
                
                return checksums
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Error loading checksums file: {str(e)}, creating new one")
    else:
        logger.debug(f"Checksums file {checksums_file} doesn't exist, starting with empty checksums")
    return {}


def save_checksums(checksums, checksums_file):
    """Save checksums to file."""
    try:
        with open(checksums_file, 'w') as f:
            json.dump(checksums, f)
        logger.debug(f"Saved {len(checksums)} checksums to {checksums_file}")
    except IOError as e:
        logger.error(f"Failed to save checksums file: {str(e)}")


def check_file_content(file_path, expected_content):
    """Check if a file exists and its content matches the expected content."""
    try:
        if not os.path.exists(file_path):
            logger.debug(f"File doesn't exist: {file_path}")
            return False
        
        with open(file_path, 'r', encoding='utf-8') as f:
            actual_content = f.read()
        
        if actual_content == expected_content:
            logger.debug(f"Content matches for file: {file_path}")
            return True
        else:
            logger.debug(f"Content differs for file: {file_path}")
            logger.debug(f"Expected content length: {len(expected_content)}")
            logger.debug(f"Actual content length: {len(actual_content)}")
            if len(expected_content) < 100 and len(actual_content) < 100:
                logger.debug(f"Expected: {expected_content}")
                logger.debug(f"Actual: {actual_content}")
            else:
                # Show just the first 50 chars of each
                logger.debug(f"Expected starts with: {expected_content[:50]}...")
                logger.debug(f"Actual starts with: {actual_content[:50]}...")
            return False
    except Exception as e:
        logger.error(f"Error checking file content: {str(e)}")
        return False


def create_strm_files_for_series(series_items, base_path, checksums=None):
    """Create folder structure and STRM files for series."""
    if checksums is None:
        checksums = {}
    
    logger.debug(f"Creating STRM files for {len(series_items)} series with {len(checksums)} existing checksums")
    series_path = os.path.join(base_path, 'series')
    os.makedirs(series_path, exist_ok=True)
    
    # No need to check filters here - already filtered in categorize_items
    
    # Skip if there are no series items
    if not series_items:
        logger.info("No series items found or selected in filters. No files will be created.")
        return 0, 0, []
    
    # Group series by name
    series_dict = {}
    for item in series_items:
        if not item.series_name:
            continue
            
        if item.series_name not in series_dict:
            series_dict[item.series_name] = []
        series_dict[item.series_name].append(item)
    
    logger.info(f"Processing {len(series_dict)} series from filter list")
    
    # Create folders and STRM files
    updated_count = 0
    unchanged_count = 0
    new_files_count = 0
    new_items_details = []  # Track details of new items for notification
    
    for series_name, episodes in series_dict.items():
        # Create series directory
        safe_series_name = sanitize_filename(series_name)
        series_dir = os.path.join(series_path, safe_series_name)
        os.makedirs(series_dir, exist_ok=True)
        
        for episode in episodes:
            if episode.season is not None and episode.episode is not None:
                # Create season directory
                season_dir = os.path.join(series_dir, f'Season {episode.season:02d}')
                os.makedirs(season_dir, exist_ok=True)
                
                # Create STRM file for episode
                episode_filename = f'{safe_series_name} S{episode.season:02d}E{episode.episode:02d}.strm'
                strm_path = os.path.join(season_dir, episode_filename)
                
                # Check if content has changed
                content_hash = calculate_content_hash(episode.url)
                file_path_rel = os.path.relpath(strm_path, base_path)
                
                # First check if file content actually differs from what we want to write
                needs_update = not check_file_content(strm_path, episode.url)
                is_new_file = not os.path.exists(strm_path)
                
                # Then check checksums 
                if file_path_rel not in checksums:
                    logger.debug(f"New file: {file_path_rel} (hash: {content_hash})")
                    needs_update = True
                    is_new_file = True
                elif checksums[file_path_rel] != content_hash:
                    logger.debug(f"Content changed: {file_path_rel} (old hash: {checksums[file_path_rel]}, new hash: {content_hash})")
                    needs_update = True
                
                if needs_update:
                    # Write URL to STRM file
                    try:
                        with open(strm_path, 'w', encoding='utf-8') as strm_file:
                            strm_file.write(episode.url)
                        
                        # Update checksum
                        checksums[file_path_rel] = content_hash
                        updated_count += 1
                        if is_new_file:
                            new_files_count += 1
                            # Add episode details for notification
                            new_items_details.append({
                                'type': 'series',
                                'name': series_name,
                                'season': episode.season,
                                'episode': episode.episode,
                                'display': f"{series_name} S{episode.season:02d}E{episode.episode:02d}"
                            })
                        logger.debug(f"{'Created new' if is_new_file else 'Updated'} STRM file: {strm_path}")
                    except IOError as e:
                        logger.error(f"Failed to write STRM file {strm_path}: {str(e)}")
                else:
                    unchanged_count += 1
    
    logger.info(f"Series: Created {new_files_count} new, updated {updated_count - new_files_count} existing STRM files, {unchanged_count} files unchanged")
    return updated_count, new_files_count, new_items_details


def create_strm_files_for_movies(movie_items, base_path, checksums=None):
    """Create folder structure and STRM files for movies."""
    if checksums is None:
        checksums = {}
    
    logger.debug(f"Creating STRM files for {len(movie_items)} movies with {len(checksums)} existing checksums")
    movies_path = os.path.join(base_path, 'movies')
    os.makedirs(movies_path, exist_ok=True)
    
    # Skip if there are no movie items
    if not movie_items:
        logger.info("No movie items found or selected in filters. No files will be created.")
        return 0, 0, []
    
    logger.info(f"Processing {len(movie_items)} movies from filter list")
    
    updated_count = 0
    unchanged_count = 0
    new_files_count = 0
    new_items_details = []  # Track details of new items for notification
    
    for movie in movie_items:
        # Extract movie name and year for folder naming
        movie_title = movie.title
        year = movie.year
        
        # Extract clean movie name without year if present in the title
        if year and f"({year})" in movie_title:
            movie_name = movie_title.replace(f"({year})", "").strip()
        else:
            movie_name = movie_title.strip()
        
        # No need to filter here - already filtered in categorize_items
        
        # Create folder name with year if available
        if year:
            folder_name = f"{movie_name} ({year})"
        else:
            folder_name = movie_name
        
        # Create movie directory
        safe_folder_name = sanitize_filename(folder_name)
        movie_dir = os.path.join(movies_path, safe_folder_name)
        os.makedirs(movie_dir, exist_ok=True)
        
        # Create STRM file
        strm_path = os.path.join(movie_dir, f"{safe_folder_name}.strm")
        
        # Check if content has changed
        content_hash = calculate_content_hash(movie.url)
        file_path_rel = os.path.relpath(strm_path, base_path)
        
        # First check if file content actually differs from what we want to write
        needs_update = not check_file_content(strm_path, movie.url)
        is_new_file = not os.path.exists(strm_path)
        
        # Then check checksums
        if file_path_rel not in checksums:
            logger.debug(f"New file: {file_path_rel} (hash: {content_hash})")
            needs_update = True
            is_new_file = True
        elif checksums[file_path_rel] != content_hash:
            logger.debug(f"Content changed: {file_path_rel} (old hash: {checksums[file_path_rel]}, new hash: {content_hash})")
            needs_update = True
        
        if needs_update:
            # Write URL to STRM file
            try:
                with open(strm_path, 'w', encoding='utf-8') as strm_file:
                    strm_file.write(movie.url)
                
                # Update checksum
                checksums[file_path_rel] = content_hash
                updated_count += 1
                if is_new_file:
                    new_files_count += 1
                    # Add movie details for notification
                    display_name = folder_name if year else movie_name
                    new_items_details.append({
                        'type': 'movie',
                        'name': display_name,
                        'display': display_name
                    })
                logger.debug(f"{'Created new' if is_new_file else 'Updated'} STRM file: {strm_path}")
            except IOError as e:
                logger.error(f"Failed to write STRM file {strm_path}: {str(e)}")
        else:
            unchanged_count += 1
    
    logger.info(f"Movies: Created {new_files_count} new, updated {updated_count - new_files_count} existing STRM files, {unchanged_count} files unchanged")
    return updated_count, new_files_count, new_items_details


def create_live_m3u_file(live_items, base_path, checksums=None):
    """Create a live.m3u file containing all live TV streams."""
    if checksums is None:
        checksums = {}
    
    logger.debug(f"Creating live.m3u file for {len(live_items)} channels")
    # Create the live.m3u file path
    live_m3u_path = os.path.join(base_path, 'live.m3u')
    
    # Skip if there are no live items
    if not live_items:
        logger.info("No live TV items found or selected in filters. No live.m3u file will be created.")
        # If an old live.m3u file exists, remove it since we have no items
        if os.path.exists(live_m3u_path):
            try:
                os.remove(live_m3u_path)
                logger.info(f"Removed old live.m3u file since no channels are selected")
            except Exception as e:
                logger.error(f"Failed to remove old live.m3u file: {str(e)}")
        return 0, 0, []
    
    # Build the M3U file content
    m3u_content = "#EXTM3U\n"
    for item in live_items:
        # Add the EXTINF line with attributes including group-title
        m3u_content += f'#EXTINF:-1 tvg-id="{item.tvg_id}" tvg-name="{item.tvg_name}" tvg-logo="{item.tvg_logo}" group-title="{item.group_title}",{item.title}\n'
        # Add the URL
        m3u_content += f'{item.url}\n'
    
    # Calculate hash of the content
    content_hash = calculate_content_hash(m3u_content)
    file_path_rel = os.path.relpath(live_m3u_path, base_path)
    
    # Check if this is a new file
    is_new_file = not os.path.exists(live_m3u_path)
    
    # First check if file content actually differs from what we want to write
    needs_update = not check_file_content(live_m3u_path, m3u_content)
    
    # Then check checksums
    if file_path_rel not in checksums:
        logger.debug(f"New live.m3u file (hash: {content_hash})")
        needs_update = True
        is_new_file = True
    elif checksums[file_path_rel] != content_hash:
        logger.debug(f"live.m3u content changed (old hash: {checksums[file_path_rel]}, new hash: {content_hash})")
        needs_update = True
    
    updated = False
    if needs_update:
        # Write content to the file
        try:
            with open(live_m3u_path, 'w', encoding='utf-8') as m3u_file:
                m3u_file.write(m3u_content)
            
            # Update checksum
            checksums[file_path_rel] = content_hash
            updated = True
            logger.info(f"{'Created new' if is_new_file else 'Updated'} live.m3u file with {len(live_items)} channels")
        except IOError as e:
            logger.error(f"Failed to write live.m3u file: {str(e)}")
    else:
        logger.info("Live.m3u file is unchanged")
        
    return (1 if updated else 0), (1 if is_new_file and updated else 0), []


def send_telegram_notification(message):
    """Send notification via Telegram bot."""
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not bot_token or not chat_id:
        logger.warning("Telegram bot token or chat ID not configured, skipping notification")
        return
        
    try:
        # Telegram Bot API endpoint for sending messages
        api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        params = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        
        response = requests.post(api_url, params=params)
        response_data = response.json()
        
        if response.status_code == 200 and response_data.get("ok"):
            logger.info("Successfully sent notification via Telegram")
        else:
            logger.error(f"Failed to send Telegram notification. Status code: {response.status_code}, Response: {response_data}")
            
    except Exception as e:
        logger.error(f"Error sending Telegram notification: {str(e)}")


def format_notification_message(new_series_details, new_movies_details, live_updated):
    """Format a detailed notification message."""
    message = "🎬 <b>Library Update</b>\n\n"
    
    # Add series details
    if new_series_details:
        message += "<b>New Series Episodes:</b>\n"
        # Group by series name
        series_groups = {}
        for item in new_series_details:
            series_name = item['name']
            if series_name not in series_groups:
                series_groups[series_name] = []
            series_groups[series_name].append(item)
            
        # Format each series with its episodes
        for series_name, episodes in series_groups.items():
            if len(episodes) == 1:
                episode = episodes[0]
                message += f"• {series_name} S{episode['season']:02d}E{episode['episode']:02d}\n"
            else:
                message += f"• {series_name}: {len(episodes)} episodes\n"
                # List up to 5 episodes
                for episode in sorted(episodes, key=lambda x: (x['season'], x['episode']))[:5]:
                    message += f"  - S{episode['season']:02d}E{episode['episode']:02d}\n"
                # Add ellipsis if more than 5 episodes
                if len(episodes) > 5:
                    message += f"  - and {len(episodes) - 5} more...\n"
        message += "\n"
    
    # Add movie details
    if new_movies_details:
        message += "<b>New Movies:</b>\n"
        # List all movies (up to 20)
        for i, movie in enumerate(new_movies_details[:20]):
            message += f"• {movie['name']}\n"
        # Add ellipsis if more than 20 movies
        if len(new_movies_details) > 20:
            message += f"• and {len(new_movies_details) - 20} more...\n"
        message += "\n"
    
    # Add live TV update message if applicable
    if live_updated:
        message += "📺 <b>Live TV channels have been updated.</b>\n\n"
    
    # Add total count
    total_new = len(new_series_details) + len(new_movies_details) + (1 if live_updated else 0)
    message += f"Total: {total_new} new items added to your media library."
    
    return message


def check_m3u_file(m3u_file):
    """Check if the M3U file exists and is readable."""
    if not m3u_file:
        logger.error("No M3U file specified")
        return False
    
    if not os.path.exists(m3u_file):
        logger.error(f"M3U file {m3u_file} does not exist")
        return False
    
    if not os.path.isfile(m3u_file):
        logger.error(f"{m3u_file} is not a file")
        return False
    
    logger.info(f"Found valid M3U file: {m3u_file}")
    return True

def download_from_url(url, destination):
    """Download an M3U file from a URL."""
    try:
        logger.info(f"Downloading M3U file from {url} to {destination}")
        response = requests.get(url, timeout=30)
        response.raise_for_status()  # Raise an exception for HTTP errors
        
        with open(destination, 'wb') as file:
            file.write(response.content)
        
        logger.info(f"Successfully downloaded M3U file to {destination}")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to download M3U file: {str(e)}")
        return False
    except IOError as e:
        logger.error(f"Failed to save downloaded M3U file: {str(e)}")
        return False

def get_m3u_file():
    """Get the path to the M3U file. Download if needed."""
    # Get M3U file path from environment variable
    m3u_file = os.getenv("M3U_FILE", "")
    m3u_url = os.getenv("M3U_URL", "")
    script_folder = os.path.dirname(os.path.abspath(__file__))
    
    logger.debug(f"M3U_FILE env: {m3u_file}, M3U_URL env: {m3u_url}")
    

    if m3u_file:
        return m3u_file
    elif m3u_url:
        logger.info(f"Downloading M3U file from URL: {m3u_url}")
        m3u_file = os.path.join(script_folder, "downloaded_playlist.m3u")

        # Check if recently downloaded
        if os.path.exists(m3u_file):
            # Get the time the file was last modified
            last_modified = os.path.getmtime(m3u_file)
            # Get the current time
            current_time = time.time()
            # Check if the file was modified in the last 5 minutes
            if current_time - last_modified < 5 * 60:
                logger.info("M3U file was recently downloaded, skipping download")
                return m3u_file
        
        # Download the file
        if download_from_url(m3u_url, m3u_file):
            return m3u_file
    else:
        logger.error("No M3U file specified. Please set M3U_FILE or M3U_URL environment variable.")
    
    return m3u_file

def refresh_jellyfin_libraries(updated_content_types):
    """Refresh Jellyfin libraries by sending a generic refresh request."""
    jellyfin_url = os.getenv("JELLYFIN_URL")
    jellyfin_api_key = os.getenv("JELLYFIN_API_KEY")
    
    if not jellyfin_url or not jellyfin_api_key:
        logger.debug("Jellyfin URL or API key not configured, skipping library refresh")
        return False
    
    try:
        # Strip trailing slash from URL if present
        jellyfin_url = jellyfin_url.rstrip('/')
        
        headers = {
            "X-MediaBrowser-Token": jellyfin_api_key,  # Use X-MediaBrowser-Token for compatibility
            "Content-Type": "application/json"
        }
        
        # Use the generic library refresh endpoint
        refresh_url = f"{jellyfin_url}/Library/Refresh"
        
        # Send an empty POST request to refresh all libraries
        response = requests.post(refresh_url, data="", headers=headers)
        response.raise_for_status()
        
        logger.info(f"Successfully triggered Jellyfin library refresh for: {', '.join(updated_content_types)}")
        return True
            
    except Exception as e:
        logger.error(f"Error refreshing Jellyfin libraries: {str(e)}")
        # Add more detailed debug info for network errors
        if isinstance(e, requests.exceptions.RequestException):
            logger.debug(f"Request error details: {e.response.text if getattr(e, 'response', None) else 'No response'}")
        return False

def run_task():
    logger.info("Task is running...")
    
    # Get or download M3U file
    m3u_file = get_m3u_file()
    
    # Check if M3U file exists and is valid
    if not check_m3u_file(m3u_file):
        logger.error("No valid M3U file found. Please specify a valid file using the M3U_FILE or M3U_URL environment variable.")
    
    # Set output directory to script folder + '/vods'
    script_folder = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_folder, 'vods')
    checksums_file = os.path.join(output_dir, ".checksums.json")
    
    # Parse and categorize M3U items
    items = parse_m3u_file(m3u_file)
    categorized_items = categorize_items(items)
    
    # Check if we have any items after filtering
    if not categorized_items['series'] and not categorized_items['movies'] and not categorized_items['live']:
        logger.warning("No items remain after applying filters. No files will be created.")
        logger.warning("Please update your filters in the web UI to include specific content.")
        return
    
    # Print summary of categorized items
    logger.info(f"Found {len(categorized_items['series'])} series items after filtering")
    logger.info(f"Found {len(categorized_items['movies'])} movie items after filtering")
    logger.info(f"Found {len(categorized_items['live'])} live TV items after filtering")
    
    # Create output directories if they don't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Load existing checksums
    checksums = load_checksums(checksums_file)
    logger.debug(f"Initial checksums count: {len(checksums)}")
    
    # Save a copy of checksums for debugging
    orig_checksums = checksums.copy()
    
    # Create STRM files for movies and series
    series_updated, series_new, new_series_details = create_strm_files_for_series(categorized_items['series'], output_dir, checksums)
    movies_updated, movies_new, new_movies_details = create_strm_files_for_movies(categorized_items['movies'], output_dir, checksums)
    live_updated, live_new, _ = create_live_m3u_file(categorized_items['live'], output_dir, checksums)
    
    # Debug: Check for changes in checksums
    new_keys = set(checksums.keys()) - set(orig_checksums.keys())
    changed_keys = {k for k in set(checksums.keys()) & set(orig_checksums.keys()) if checksums[k] != orig_checksums[k]}
    if new_keys:
        logger.debug(f"New checksums added: {len(new_keys)}")
        if logger.isEnabledFor(logging.DEBUG) and len(new_keys) < 10:
            logger.debug(f"New files: {', '.join(new_keys)}")
    if changed_keys:
        logger.debug(f"Checksums changed: {len(changed_keys)}")
        if logger.isEnabledFor(logging.DEBUG) and len(changed_keys) < 10:
            logger.debug(f"Changed files: {', '.join(changed_keys)}")
            for k in changed_keys:
                logger.debug(f"  {k}: {orig_checksums[k]} -> {checksums[k]}")
    
    # Save checksums
    logger.debug(f"Final checksums count: {len(checksums)}")
    save_checksums(checksums, checksums_file)
    
    total_updated = series_updated + movies_updated + live_updated
    total_new = series_new + movies_new + live_new
    
    if total_updated > 0:
        logger.info(f"File creation complete. Created {total_new} new files, updated {total_updated - total_new} existing files.")
        
        # Refresh Jellyfin libraries based on what content was updated
        updated_content_types = []
        if series_updated > 0:
            updated_content_types.append('series')
        if movies_updated > 0:
            updated_content_types.append('movies')
        if live_updated > 0:
            updated_content_types.append('live')
            
        if updated_content_types:
            refresh_result = refresh_jellyfin_libraries(updated_content_types)
            if refresh_result:
                logger.info("Successfully refreshed Jellyfin libraries")
        
        # Send user notification only for new files
        if total_new > 0:
            # Create detailed message
            notification_message = format_notification_message(
                new_series_details,
                new_movies_details,
                live_new > 0
            )
            send_telegram_notification(notification_message)
    else:
        logger.info("No changes detected, all files are up to date.")


# Start the web UI in a separate thread
def start_web_ui_thread():
    # Try to find or download M3U file before starting the web UI
    m3u_file = get_m3u_file()
    
    if not m3u_file or not os.path.exists(m3u_file):
        logger.warning("No valid M3U file found before starting web UI")
    
    web_thread = threading.Thread(target=web_ui.start_web_ui)
    web_thread.daemon = True
    web_thread.start()
    logger.info(f"Web UI started on port {web_ui.WEB_UI_PORT}")

# Global variable to store the last time the task was run
last_run_time = 0

# Function to rerun the task
def rerun_task():
    """Manually trigger the task to run"""
    logger.info("Manually triggering task run (likely from web UI)")
    global last_run_time
    # Only run if it's been at least 10 seconds since last run to prevent spam
    current_time = time.time()
    if current_time - last_run_time > 10:
        last_run_time = current_time
        # Run in a separate thread to not block the web UI
        task_thread = threading.Thread(target=lambda: run_task())
        task_thread.daemon = True
        task_thread.start()
        return True
    else:
        logger.warning("Task run requested but rejected (ran too recently)")
        return False

def ensure_config_directory():
    """Make sure the config directory exists and migrate env vars if needed"""
    config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config')
    os.makedirs(config_dir, exist_ok=True)
    
    filters_file = os.path.join(config_dir, 'filters.json')
    
    # If filters file doesn't exist, try to create it from environment variables
    if not os.path.exists(filters_file):
        filters = {
            'series': [],
            'movies': [],
            'live': [],
            'series_groups': [],
            'movies_groups': [],
            'live_groups': []
        }
        
        # Check for legacy environment variables
        include_series = os.getenv("INCLUDE_SERIES", "")
        include_movies = os.getenv("INCLUDE_MOVIES", "")
        include_live = os.getenv("INCLUDE_LIVE", "")
        series_groups = os.getenv("SERIES_GROUPS", "")
        movies_groups = os.getenv("MOVIES_GROUPS", "")
        live_groups = os.getenv("LIVE_GROUPS", "")
        
        if include_series:
            filters['series'] = [s.strip() for s in include_series.split(",") if s.strip()]
        if include_movies:
            filters['movies'] = [m.strip() for m in include_movies.split(",") if m.strip()]
        if include_live:
            filters['live'] = [l.strip() for l in include_live.split(",") if l.strip()]

        
        # Save to config file
        try:
            with open(filters_file, 'w') as f:
                json.dump(filters, f, indent=2)
            logger.info(f"Created initial filters.json from environment variables")
        except Exception as e:
            logger.error(f"Error creating initial filters.json: {str(e)}")

    # Check for filter update signal file
    signal_file = os.path.join(config_dir, '.filters_updated')
    if os.path.exists(signal_file):
        try:
            # Get modification time to avoid re-running too frequently
            mod_time = os.path.getmtime(signal_file)
            current_time = time.time()
            
            # Only react to recent updates (within last 30 seconds)
            if current_time - mod_time < 30:
                logger.info("Detected filters update, rerunning task")
                # Remove the signal file
                os.remove(signal_file)
                # Rerun the task
                return rerun_task()
            else:
                # File is old, remove it
                os.remove(signal_file)
        except Exception as e:
            logger.error(f"Error handling filters update signal: {str(e)}")
    
    return False

if __name__ == "__main__":
    try:      
        # Log system information
        script_folder = os.path.dirname(os.path.abspath(__file__))
        logger.info(f"Starting application from {script_folder}")
        logger.debug(f"Current directory: {os.getcwd()}")
        logger.debug(f"M3U_FILE environment variable: {os.getenv('M3U_FILE', 'not set')}")
        logger.debug(f"M3U_URL environment variable: {os.getenv('M3U_URL', 'not set')}")
        
        # Ensure config directory exists and migrate env vars if needed
        ensure_config_directory()
        
        # Start the web UI
        start_web_ui_thread()
        
        # Create initial directory structure
        output_dir = os.path.join(script_folder, 'vods')
        os.makedirs(os.path.join(output_dir, "series"), exist_ok=True)
        os.makedirs(os.path.join(output_dir, "movies"), exist_ok=True)

        INTERVAL = int(os.getenv("TASK_INTERVAL", 5))  # Default to 5 minutes if not set
        logger.info(f"Task will run every {INTERVAL} minutes")
        
        while True:
            run_task()
            
            logger.info(f"Sleeping for {INTERVAL} minutes")
            time.sleep(INTERVAL * 60)
        
    except Exception as e:
        logger.error(f"An error occurred: {str(e)}", exc_info=True)  # Include traceback
        print(f"An error occurred: {e}")
