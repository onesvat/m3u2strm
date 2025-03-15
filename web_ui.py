import os
import json
from flask import Flask, render_template, request, redirect, url_for
import logging
import time

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__)
WEB_UI_PORT = int(os.getenv("WEB_UI_PORT", 5500))

# Create config directory if it doesn't exist
CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config')
os.makedirs(CONFIG_DIR, exist_ok=True)
FILTERS_FILE = os.path.join(CONFIG_DIR, 'filters.json')

def load_filters():
    """Load filters from config file or environment variables for backward compatibility"""
    filters = {
        'series': [],
        'movies': [],
        'live': [],
    }

    # Try to load from config file first
    if os.path.exists(FILTERS_FILE):
        try:
            with open(FILTERS_FILE, 'r') as f:
                filters = json.load(f)
            logger.info(f"Loaded filters from {FILTERS_FILE}")
            return filters
        except Exception as e:
            logger.error(f"Error loading filters from {FILTERS_FILE}: {str(e)}")

    return filters

def save_filters(filters):
    """Save filters to config file"""
    from task import rerun_task

    try:
        config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config')
        os.makedirs(config_dir, exist_ok=True)
        
        # Save the filters
        with open(os.path.join(config_dir, 'filters.json'), 'w') as f:
            json.dump(filters, f, indent=2)
            
        rerun_task()
            
        logger.info(f"Saved filters to {FILTERS_FILE}")
        return True
    except Exception as e:
        logger.error(f"Error saving filters to {FILTERS_FILE}: {str(e)}")
        return False

@app.route("/")
def index():
    from task import parse_m3u_file, categorize_items, get_m3u_file
    
    # Get the current filters
    filters = load_filters()
    include_series = filters.get('series', [])
    include_movies = filters.get('movies', [])
    include_live = filters.get('live', [])
    
    # Check if any filters are defined
    has_filters = bool(include_series or include_movies or include_live)
    
    # Try to get the M3U file
    m3u_file = get_m3u_file()
    
    if not m3u_file or not os.path.exists(m3u_file):
        return render_template('index.html', 
                              series=[], movies=[], live_tv=[],
                              include_series=include_series,
                              include_movies=include_movies,
                              include_live=include_live,
                              has_filters=has_filters,
                              filters_mandatory=True,
                              error="No valid M3U file found")

    # Parse M3U file
    try:
        items = parse_m3u_file(m3u_file)
        categorized = categorize_items(items, True)

        # Get all series info - handle both dict and list types
        all_series_names = sorted(set(s.series_name for s in categorized['series']))

        # Get all movie info - handle both dict and list types
        all_movie_names = sorted(set(m.title for m in categorized['movies']))

        # Handle live TV
        all_live = categorized['live']

        # Return the page with data
        return render_template('index.html', 
                              series=all_series_names,
                              movies=all_movie_names,
                              live_tv=all_live,
                              include_series=include_series,
                              include_movies=include_movies,
                              include_live=include_live,
                              has_filters=has_filters,
                              filters_mandatory=True)
    except Exception as e:
        logger.error(f"Error processing M3U file: {str(e)}", exc_info=True)
        return render_template('index.html', 
                              series=[], movies=[], live_tv=[],
                              include_series=include_series,
                              include_movies=include_movies,
                              include_live=include_live,
                              has_filters=has_filters,
                              filters_mandatory=True,
                              error=f"Error processing M3U file: {str(e)}")

@app.route("/update_filters", methods=["POST"])
def update_filters():
    # Get selected items from form
    include_series = request.form.getlist("include_series")
    include_movies = request.form.getlist("include_movies")
    include_live = request.form.getlist("include_live")
    
    # Save to config file
    filters = {
        'series': include_series,
        'movies': include_movies,
        'live': include_live,
    }
    save_filters(filters)
    
    # Redirect back to main page
    return redirect(url_for("index"))

def start_web_ui():
    """Start the web UI server"""
    app.run(host='0.0.0.0', port=WEB_UI_PORT)

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=WEB_UI_PORT, debug=True)
