import os
import time
import requests
import re
import shutil
from pathlib import Path
import hashlib
import json
import logging

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


def clean_channel_title(title):
    """Remove quality indicators (HD, FHD, SD, etc.) from channel titles."""
    # Remove common quality indicators
    cleaned = re.sub(r'\s+(FHD|HD|SD|UHD|4K)(\s+|$)', ' ', title, flags=re.IGNORECASE)
    # Remove additional formatting that might be present
    cleaned = re.sub(r'\s+\(\d+p\)(\s+|$)', ' ', cleaned)
    # Remove leading/trailing whitespace
    return cleaned.strip()


def categorize_items(items):
    series_groups = os.getenv("SERIES_GROUPS", "").split(",")
    movies_groups = os.getenv("MOVIES_GROUPS", "").split(",")
    live_groups = os.getenv("LIVE_GROUPS", "").split(",")
    
    series_items = []
    movie_items = []
    live_items = []
    
    # For live channels, we'll use a dictionary to track the best version of each channel
    channel_dict = {}
    
    for item in items:
        group = item['group_title']
        
        # Process TV series
        if any(series_group.strip().lower() in group.lower() for series_group in series_groups if series_group.strip()):
            # Parse series information: show name, season, episode
            series_info = parse_series_info(item['title'])
            if series_info:
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
        
        # Process movies
        elif any(movie_group.strip().lower() in group.lower() for movie_group in movies_groups if movie_group.strip()):
            year = extract_movie_year(item['title'])
            movie_item = MovieItem(
                title=item['title'],
                url=item['url'],
                group_title=group,
                tvg_id=item['tvg_id'],
                tvg_name=item['tvg_name'],
                tvg_logo=item['tvg_logo'],
                year=year
            )
            movie_items.append(movie_item)
        
        # Process live TV with deduplication
        elif any(live_group.strip().lower() in group.lower() for live_group in live_groups if live_group.strip()):
            # Clean the title to remove quality indicators
            clean_title = clean_channel_title(item['title'])
            
            # Use tvg_id as primary key, fall back to clean title if tvg_id is not available
            channel_key = item['tvg_id'] if item['tvg_id'] else clean_title
            
            # Check if we should replace an existing channel with this one
            if channel_key not in channel_dict:
                # First time seeing this channel, add it
                channel_dict[channel_key] = item
            else:
                # We already have a version of this channel
                # Prioritize FHD over HD over SD
                current_title = channel_dict[channel_key]['title'].upper()
                new_title = item['title'].upper()
                
                if 'FHD' in new_title and 'FHD' not in current_title:
                    # Replace with FHD version
                    channel_dict[channel_key] = item
                # If both are FHD or both are not FHD, keep the existing one
    
    # Create LiveTVItem objects from the deduplicated channels
    for item in channel_dict.values():
        clean_title = clean_channel_title(item['title'])
        live_item = LiveTVItem(
            title=clean_title,  # Use cleaned title
            url=item['url'],
            group_title="",     # Remove group title as requested
            tvg_id=item['tvg_id'],
            tvg_name=item['tvg_name'],
            tvg_logo=item['tvg_logo'],
        )
        live_items.append(live_item)
    
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
    
    # Get the included series list from environment variable
    included_series = os.getenv("INCLUDE_SERIES", "")
    if included_series:
        included_series_list = [s.strip().lower() for s in included_series.split(",") if s.strip()]
        logger.info(f"Filtering series to include only: {', '.join(included_series_list)}")
    else:
        included_series_list = []
    
    # Group series by name
    series_dict = {}
    for item in series_items:
        if not item.series_name:
            continue
        
        # Skip series not in the included list if filtering is active
        if included_series_list and item.series_name.lower() not in included_series_list:
            logger.debug(f"Skipping series not in included list: {item.series_name}")
            continue
            
        if item.series_name not in series_dict:
            series_dict[item.series_name] = []
        series_dict[item.series_name].append(item)
    
    if included_series_list:
        logger.info(f"Found {len(series_dict)} matching series out of {len(included_series_list)} requested")
    
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
    
    # Get the included movies list from environment variable
    included_movies = os.getenv("INCLUDE_MOVIES", "")
    if included_movies:
        included_movies_list = [m.strip().lower() for m in included_movies.split(",") if m.strip()]
        logger.info(f"Filtering movies to include only: {', '.join(included_movies_list)}")
    else:
        included_movies_list = []
    
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
        
        # Skip movies not in the included list if filtering is active
        if included_movies_list and movie_name.lower() not in included_movies_list:
            logger.debug(f"Skipping movie not in included list: {movie_name}")
            continue
        
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
    
    if included_movies_list:
        logger.info(f"Movies: Created {new_files_count} new, updated {updated_count - new_files_count} existing STRM files, {unchanged_count} files unchanged (filtered by inclusion list)")
    else:
        logger.info(f"Movies: Created {new_files_count} new, updated {updated_count - new_files_count} existing STRM files, {unchanged_count} files unchanged")
    return updated_count, new_files_count, new_items_details


def create_live_m3u_file(live_items, base_path, checksums=None):
    """Create a live.m3u file containing all live TV streams."""
    if checksums is None:
        checksums = {}
    
    logger.debug(f"Creating live.m3u file for {len(live_items)} channels")
    # Create the live.m3u file path
    live_m3u_path = os.path.join(base_path, 'live.m3u')
    
    # Build the M3U file content
    m3u_content = "#EXTM3U\n"
    for item in live_items:
        # Add the EXTINF line with attributes but without group-title
        m3u_content += f'#EXTINF:-1 tvg-id="{item.tvg_id}" tvg-name="{item.tvg_name}" tvg-logo="{item.tvg_logo}",{item.title}\n'
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


def run_task():
    logger.info("Task is running...")
    m3u_file = os.getenv("M3U_FILE", "m3u_file.m3u")
    # Set output directory to script folder + '/vods'
    script_folder = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_folder, 'vods')
    checksums_file = os.path.join(output_dir, ".checksums.json")
    
    # Check if file exists
    if not os.path.exists(m3u_file):
        logger.error(f"M3U file {m3u_file} does not exist")
        return
    
    # Parse and categorize M3U items
    items = parse_m3u_file(m3u_file)
    categorized_items = categorize_items(items)
    
    # Print summary of categorized items
    logger.info(f"Found {len(categorized_items['series'])} series items")
    logger.info(f"Found {len(categorized_items['movies'])} movie items")
    logger.info(f"Found {len(categorized_items['live'])} live TV items")
    
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


if __name__ == "__main__":
    logger.info("Starting m3u2strm converter")
    M3U_FILE = os.getenv("M3U_FILE")
    if M3U_FILE:
        logger.info(f"Using provided M3U file: {M3U_FILE}")
    else:
        M3U_URL = os.getenv("M3U_URL")
        if M3U_URL:
            download_m3u_file(M3U_URL, "m3u_file.m3u")
        else:
            logger.warning("M3U_URL environment variable is not set")

    # Create initial directory structure
    script_folder = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_folder, 'vods')
    os.makedirs(os.path.join(output_dir, "series"), exist_ok=True)
    os.makedirs(os.path.join(output_dir, "movies"), exist_ok=True)

    INTERVAL = int(os.getenv("TASK_INTERVAL", 5))  # Default to 5 minutes if not set
    logger.info(f"Task will run every {INTERVAL} minutes")
    while True:
        run_task()
        logger.info(f"Sleeping for {INTERVAL} minutes")
        time.sleep(INTERVAL * 60)
