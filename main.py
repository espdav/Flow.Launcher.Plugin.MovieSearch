# -*- coding: utf-8 -*-

import sys
from pathlib import Path

plugindir = Path.absolute(Path(__file__).parent)
paths = (".", "lib", "plugin")
sys.path = [str(plugindir / p) for p in paths] + sys.path

import os
import json
import requests
import webbrowser
import logging
from typing import List, Dict, Any
from datetime import datetime, timedelta

from flowlauncher import FlowLauncher

# Set up logging
log_file = os.path.join(plugindir, 'tmdb_plugin.log')
logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

TMDB_API_KEY = 'ac09bcf3d1952c1e258c0b891c5f6c0f'  # Replace this with your actual TMDB key
TMDB_IMAGE_BASE_URL = 'https://image.tmdb.org/t/p/w92'  # w92 is a good size for icons

class TMDBMovieSearch(FlowLauncher):
    def __init__(self):
        try:
            self.cache_file = os.path.join(plugindir, 'popular_movies_cache.json')
            self.cache = self._load_cache()
            # tiny runtime cache for directors/creators to avoid duplicate requests in same session
            self._people_cache: Dict[str, str] = {}
            super().__init__()
        except Exception as e:
            logging.error(f"Error initializing plugin: {str(e)}")
            raise

    def _load_cache(self) -> Dict:
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                    if datetime.fromisoformat(cache['timestamp']) > datetime.now() - timedelta(hours=24):
                        return cache
        except Exception as e:
            logging.error(f"Error loading cache: {str(e)}")
        return {'timestamp': datetime.now().isoformat(), 'movies': []}

    def _save_cache(self, movies: List[Dict]):
        try:
            cache = {
                'timestamp': datetime.now().isoformat(),
                'movies': movies
            }
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache, f)
        except Exception as e:
            logging.error(f"Error saving cache: {str(e)}")

    def _get_popular_movies(self) -> List[Dict]:
        if not self.cache['movies']:
            try:
                url = f'https://api.themoviedb.org/3/movie/popular?api_key={TMDB_API_KEY}&page=1'
                response = requests.get(url, timeout=5)
                response.raise_for_status()
                movies = response.json().get('results', [])
                movies.sort(key=lambda x: x.get('popularity', 0), reverse=True)
                movies = movies[:50]
                self._save_cache(movies)
                return movies
            except Exception as e:
                logging.error(f"Error fetching popular movies: {str(e)}")
                return []
        return self.cache['movies']

    def _get_movie_details(self, movie_id: int) -> Dict:
        try:
            url = f'https://api.themoviedb.org/3/movie/{movie_id}?api_key={TMDB_API_KEY}&append_to_response=external_ids'
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logging.error(f"Error fetching movie details for ID {movie_id}: {str(e)}")
            return {}

    def _get_tv_details(self, tv_id: int) -> Dict:
        try:
            url = f'https://api.themoviedb.org/3/tv/{tv_id}?api_key={TMDB_API_KEY}&append_to_response=external_ids'
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logging.error(f"Error fetching tv details for ID {tv_id}: {str(e)}")
            return {}

    # --------------------
    # new helpers: director / creators (with caching + fallbacks)
    # --------------------
    def _get_movie_director(self, movie_id: int) -> str:
        """Return director name(s) for a movie. cached as 'movie:{id}'"""
        cache_key = f"movie:{movie_id}"
        if cache_key in self._people_cache:
            return self._people_cache[cache_key]

        try:
            url = f"https://api.themoviedb.org/3/movie/{movie_id}/credits?api_key={TMDB_API_KEY}"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            credits = response.json()
            crew = credits.get("crew", [])
            # collect all crew members whose job == "Director"
            directors = [c.get("name") for c in crew if c.get("job") and c.get("job").lower() == "director"]
            if directors:
                val = ", ".join(directors)
                self._people_cache[cache_key] = val
                return val
            # fallback to "Unknown"
            self._people_cache[cache_key] = "Unknown"
            return "Unknown"
        except Exception as e:
            logging.error(f"Error fetching director for movie {movie_id}: {str(e)}")
            self._people_cache[cache_key] = "Unknown"
            return "Unknown"

    def _get_tv_creators(self, tv_id: int) -> str:
        """
        Return creator name(s) for a tv series.
        first try aggregate_credits (parsing crew[].jobs[]), then fall back to details.created_by
        cached as 'tv:{id}'
        """
        cache_key = f"tv:{tv_id}"
        if cache_key in self._people_cache:
            return self._people_cache[cache_key]

        # try aggregate_credits
        try:
            url = f"https://api.themoviedb.org/3/tv/{tv_id}/aggregate_credits?api_key={TMDB_API_KEY}"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            data = response.json()
            crew = data.get("crew", [])
            creators = []
            for person in crew:
                jobs = person.get("jobs", [])
                # jobs is an array of objects with a 'job' key
                for j in jobs:
                    job_name = j.get("job", "")
                    if job_name and job_name.lower() == "creator":
                        name = person.get("name")
                        if name and name not in creators:
                            creators.append(name)
            if creators:
                val = ", ".join(creators)
                self._people_cache[cache_key] = val
                return val
        except Exception as e:
            # log but continue to fallback
            logging.debug(f"aggregate_credits not usable for tv {tv_id}: {e}")

        # fallback: use tv details 'created_by' if present
        try:
            details = self._get_tv_details(tv_id)
            created_by = details.get("created_by", [])
            names = [c.get("name") for c in created_by if c.get("name")]
            if names:
                val = ", ".join(names)
                self._people_cache[cache_key] = val
                return val
        except Exception as e:
            logging.error(f"Error fetching created_by fallback for tv {tv_id}: {str(e)}")

        self._people_cache[cache_key] = "Unknown"
        return "Unknown"

    # --------------------
    # main query (kept mostly as you had it)
    # --------------------
    def query(self, query: str) -> List[Dict[str, Any]]:
        try:
            if not query or query.isspace():
                return [{
                    "Title": "Enter a movie or tv series title",
                    "SubTitle": "Type the name after 'imdb' to search",
                    "IcoPath": "image/icon.png"
                }]

            query = query.lower()
            items = []

            # movie search
            search_url_movie = f'https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={query}&page=1'
            results_movie = []
            try:
                response = requests.get(search_url_movie, timeout=5)
                response.raise_for_status()
                results_movie = response.json().get('results', [])
            except Exception as e:
                logging.error(f"Error searching movies: {str(e)}")

            for movie in results_movie[:5]:
                items.append(self._format_movie_item(movie))

            # tv search
            search_url_tv = f'https://api.themoviedb.org/3/search/tv?api_key={TMDB_API_KEY}&query={query}&page=1'
            results_tv = []
            try:
                response = requests.get(search_url_tv, timeout=5)
                response.raise_for_status()
                results_tv = response.json().get('results', [])
            except Exception as e:
                logging.error(f"Error searching tv: {str(e)}")

            for show in results_tv[:5]:
                items.append(self._format_tv_item(show))

            if not items:
                return [{
                    "Title": "No results found",
                    "SubTitle": f"No results found for '{query}'",
                    "IcoPath": "image/icon.png"
                }]

            return items
        except Exception as e:
            logging.error(f"Unexpected error in query: {str(e)}")
            return [{
                "Title": "Error",
                "SubTitle": "An unexpected error occurred. Check the log file for details.",
                "IcoPath": "image/icon.png"
            }]

    # --------------------
    # formatters (now include director / creator in title)
    # --------------------
    def _format_movie_item(self, movie: Dict) -> Dict[str, Any]:
        try:
            title = movie.get('title', 'No Title')
            rating = movie.get('vote_average', None)
            rating = f"{round(rating, 1):.1f}" if rating is not None else "N/A"
            overview = movie.get('overview', 'No overview available.')
            release_date = movie.get('release_date', 'N/A')
            movie_id = movie.get('id')
            poster_path = movie.get('poster_path')

            ico_path = f"{TMDB_IMAGE_BASE_URL}/{poster_path.lstrip('/')}" if poster_path else "image/icon.png"
            year = release_date.split('-')[0] if release_date != 'N/A' else ''
            display_title = f"{title} ({year})" if year else title

            # get director (may be "Unknown")
            #director = self._get_movie_director(movie_id)

            return {
                "Title": f"{display_title} - ⭐ {rating}/10",
                "SubTitle": overview[:150] + "..." if len(overview) > 150 else overview,
                "IcoPath": ico_path,
                "JsonRPCAction": {
                    "method": "open_movie",
                    "parameters": [movie_id],
                    "dontHideAfterAction": False
                },
                "ContextData": {
                    "type": "movie",
                    "id": movie_id,
                    "overview": overview
                }
            }
        except Exception as e:
            logging.error(f"Error formatting movie item: {str(e)}")
            return {
                "Title": "Error formatting movie",
                "SubTitle": "There was an error displaying this movie",
                "IcoPath": "image/icon.png"
            }

    def _format_tv_item(self, show: Dict) -> Dict[str, Any]:
        try:
            name = show.get('name', 'No Title')
            rating = show.get('vote_average', None)
            rating = f"{round(rating, 1):.1f}" if rating is not None else "N/A"
            overview = show.get('overview', 'No overview available.')
            first_air_date = show.get('first_air_date', 'N/A')
            tv_id = show.get('id')
            poster_path = show.get('poster_path')

            ico_path = f"{TMDB_IMAGE_BASE_URL}/{poster_path.lstrip('/')}" if poster_path else "image/icon.png"
            year = first_air_date.split('-')[0] if first_air_date != 'N/A' else ''
            display_title = f"{name} ({year})" if year else name

            # get creator(s)
            #creator = self._get_tv_creators(tv_id)

            return {
                "Title": f"{display_title} - ⭐ {rating}/10",
                "SubTitle": overview[:150] + "..." if len(overview) > 150 else overview,
                "IcoPath": ico_path,
                "JsonRPCAction": {
                    "method": "open_tv",
                    "parameters": [tv_id],
                    "dontHideAfterAction": False
                },
                "ContextData": {
                    "type": "tv",
                    "id": tv_id,
                    "overview": overview
                }
            }
        except Exception as e:
            logging.error(f"Error formatting tv item: {str(e)}")
            return {
                "Title": "Error formatting tv show",
                "SubTitle": "There was an error displaying this tv show",
                "IcoPath": "image/icon.png"
            }

    # --------------------
    # context menu (uses the helper functions and aggregate_credits for tv cast)
    # --------------------
    def context_menu(self, data):
        try:
            item_type = data.get("type")
            item_id = data.get("id")
            overview = data.get("overview", "")

            if not item_type or not item_id:
                return []

            # fetch details (to get imdb_id)
            details = self._get_movie_details(item_id) if item_type == "movie" else self._get_tv_details(item_id)
            imdb_id = details.get('external_ids', {}).get('imdb_id', '')

            context_items = []

            # directors or creators using helper functions
            if item_type == "movie":
                title = "Directed by " + self._get_movie_director(item_id)
                # credits endpoint for movie cast
                credits_url = f"https://api.themoviedb.org/3/movie/{item_id}/credits?api_key={TMDB_API_KEY}"
            else:
                title = "Created by " + self._get_tv_creators(item_id)
                # use aggregate_credits for tv cast/crew
                credits_url = f"https://api.themoviedb.org/3/tv/{item_id}/aggregate_credits?api_key={TMDB_API_KEY}"

            # try fetch credits (for cast preview)
            try:
                r = requests.get(credits_url, timeout=5)
                r.raise_for_status()
                credits = r.json()
            except Exception as e:
                logging.error(f"Error fetching credits for context menu {item_type} {item_id}: {str(e)}")
                credits = {}

            # link to external page (imdb if available, otherwise tmdb)
            if imdb_id:
                credits_link = f"https://www.imdb.com/title/{imdb_id}/fullcredits/"
                page_link = f"https://www.imdb.com/title/{imdb_id}"
            else:
                # tmdb fallback
                if item_type == "movie":
                    credits_link = f"https://www.themoviedb.org/movie/{item_id}/credits"
                    page_link = f"https://www.themoviedb.org/movie/{item_id}"
                else:
                    credits_link = f"https://www.themoviedb.org/tv/{item_id}/aggregate_credits"
                    page_link = f"https://www.themoviedb.org/tv/{item_id}"

            context_items.append({
                "Title": title if title else ("No director info" if item_type == "movie" else "No creator info"),
                "SubTitle": "Click to visit the writer page on imdb",
                "IcoPath": "image/director-chair.png",
                "JsonRPCAction": {
                    "method": "open_url",
                    "parameters": [credits_link]
                }
            })

            # cast (first up to 3)
            cast = credits.get("cast", [])
            cast_names = []
            for c in cast[:3]:
                name = c.get("name")
                if name:
                    cast_names.append(name)
            if cast_names:
                context_items.append({
                    "Title": "Star: " + ", ".join(cast_names),
                    "SubTitle": "Click to visit the full cast on imdb",
                    "IcoPath": "image/star.png",
                    "JsonRPCAction": {
                        "method": "open_url",
                        "parameters": [credits_link]  # fullcredits page covers cast too (IMDB or TMDB)
                    }
                })

            # description / open page
            context_items.append({
                "Title": overview or "No overview available.",
                "SubTitle": "Click to visit the imdb page",
                "IcoPath": "image/popcorn.png",
                "JsonRPCAction": {
                    "method": "open_url",
                    "parameters": [page_link]
                }
            })

            return context_items
        except Exception as e:
            logging.error(f"error building context menu: {str(e)}")
            return []

    # --------------------
    # open handlers
    # --------------------
    def open_movie(self, movie_id: int) -> None:
        try:
            movie_details = self._get_movie_details(movie_id)
            imdb_id = movie_details.get('external_ids', {}).get('imdb_id', '')
            if imdb_id:
                webbrowser.open(f"https://www.imdb.com/title/{imdb_id}")
            else:
                webbrowser.open(f"https://www.themoviedb.org/movie/{movie_id}")
        except Exception as e:
            logging.error(f"Error opening movie {movie_id}: {str(e)}")

    def open_tv(self, tv_id: int) -> None:
        try:
            tv_details = self._get_tv_details(tv_id)
            imdb_id = tv_details.get('external_ids', {}).get('imdb_id', '')
            if imdb_id:
                webbrowser.open(f"https://www.imdb.com/title/{imdb_id}")
            else:
                webbrowser.open(f"https://www.themoviedb.org/tv/{tv_id}")
        except Exception as e:
            logging.error(f"Error opening tv {tv_id}: {str(e)}")

    def open_url(self, url: str) -> None:
        try:
            webbrowser.open(url)
        except Exception as e:
            logging.error(f"Error opening url {url}: {str(e)}")

if __name__ == "__main__":
    try:
        TMDBMovieSearch()
    except Exception as e:
        logging.critical(f"Critical error in plugin: {str(e)}")
        print(json.dumps({
            "result": [{
                "Title": "Critical Error",
                "SubTitle": "The plugin encountered a critical error. Check the log file for details.",
                "IcoPath": "image/icon.png"
            }]
        }))
