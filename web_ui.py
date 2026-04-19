import os
import json
from flask import Flask, render_template, request, redirect, url_for, jsonify
import logging
import time

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
WEB_UI_PORT = int(os.getenv("WEB_UI_PORT", 5500))

CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config")
os.makedirs(CONFIG_DIR, exist_ok=True)
FILTERS_FILE = os.path.join(CONFIG_DIR, "filters.json")


def load_filters():
    """Load filters from config file or environment variables for backward compatibility"""
    filters = {
        "series": [],
        "movies": [],
        "live": [],
    }

    if os.path.exists(FILTERS_FILE):
        try:
            with open(FILTERS_FILE, "r") as f:
                filters = json.load(f)
            logger.info(f"Loaded filters from {FILTERS_FILE}")
            return filters
        except Exception as e:
            logger.error(f"Error loading filters from {FILTERS_FILE}: {str(e)}")

    return filters


def save_filters(filters, trigger_task=True):
    """Save filters to config file. Optionally skip task rerun."""
    try:
        config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config")
        os.makedirs(config_dir, exist_ok=True)

        with open(os.path.join(config_dir, "filters.json"), "w") as f:
            json.dump(filters, f, indent=2)

        if trigger_task:
            from task import rerun_task

            rerun_task()

        logger.info(f"Saved filters to {FILTERS_FILE}")
        return True
    except Exception as e:
        logger.error(f"Error saving filters to {FILTERS_FILE}: {str(e)}")
        return False


@app.route("/")
def index():
    from task import (
        parse_m3u_file,
        categorize_items,
        get_m3u_file,
        get_recently_added_items,
    )

    filters = load_filters()
    include_series = filters.get("series", [])
    include_movies = filters.get("movies", [])
    include_live = filters.get("live", [])

    has_filters = bool(include_series or include_movies or include_live)

    m3u_file = get_m3u_file()

    if not m3u_file or not os.path.exists(m3u_file):
        return render_template(
            "index.html",
            series=[],
            movies=[],
            live_tv=[],
            include_series=include_series,
            include_movies=include_movies,
            include_live=include_live,
            has_filters=has_filters,
            filters_mandatory=True,
            recently_added=[],
            error="No valid M3U file found",
        )

    try:
        items = parse_m3u_file(m3u_file)
        categorized = categorize_items(items, True)

        all_series_names = sorted(set(s.series_name for s in categorized["series"]))
        all_movie_names = sorted(set(m.title for m in categorized["movies"]))
        all_live = categorized["live"]

        recent_limit = int(os.getenv("RECENTLY_ADDED_LIMIT", "100"))
        recently_added = get_recently_added_items(m3u_file, recent_limit)

        for item in recently_added:
            if item["content_type"] == "series":
                item["is_selected"] = item["title"] in include_series
            elif item["content_type"] == "movie":
                item["is_selected"] = item["title"] in include_movies
            else:
                item["is_selected"] = item["title"] in include_live

        return render_template(
            "index.html",
            series=all_series_names,
            movies=all_movie_names,
            live_tv=all_live,
            include_series=include_series,
            include_movies=include_movies,
            include_live=include_live,
            has_filters=has_filters,
            filters_mandatory=True,
            recently_added=recently_added,
        )
    except Exception as e:
        logger.error(f"Error processing M3U file: {str(e)}", exc_info=True)
        return render_template(
            "index.html",
            series=[],
            movies=[],
            live_tv=[],
            include_series=include_series,
            include_movies=include_movies,
            include_live=include_live,
            has_filters=has_filters,
            filters_mandatory=True,
            recently_added=[],
            error=f"Error processing M3U file: {str(e)}",
        )


@app.route("/toggle_item", methods=["POST"])
def toggle_item():
    """Toggle selection of a single item (AJAX)."""
    data = request.get_json()
    item_type = data.get("type")
    item_title = data.get("title")

    if not item_type or not item_title:
        return jsonify({"success": False, "error": "Missing parameters"}), 400

    type_map = {"series": "series", "movie": "movies", "live": "live"}
    if item_type not in type_map:
        return jsonify({"success": False, "error": "Invalid type"}), 400

    filters = load_filters()
    filter_key = type_map[item_type]

    filter_list = filters.get(filter_key, [])
    item_title_lower = item_title.lower()

    found = False
    for i, f in enumerate(filter_list):
        if f.lower() == item_title_lower:
            filters[filter_key].pop(i)
            selected = False
            found = True
            break

    if not found:
        filters[filter_key].append(item_title)
        selected = True

    save_filters(filters, trigger_task=False)

    return jsonify({"success": True, "selected": selected})


@app.route("/save_and_generate", methods=["POST"])
def save_and_generate():
    data = request.get_json()
    include_series = data.get("series", [])
    include_movies = data.get("movies", [])
    include_live = data.get("live", [])

    filters = {
        "series": include_series,
        "movies": include_movies,
        "live": include_live,
    }
    save_filters(filters)

    return jsonify({"success": True})


def start_web_ui():
    """Start the web UI server"""
    app.run(host="0.0.0.0", port=WEB_UI_PORT)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=WEB_UI_PORT, debug=True)
