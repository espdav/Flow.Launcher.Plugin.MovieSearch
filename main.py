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
            super().__init__()
        except Exception as e:
            logging.error(f"Error initializing plugin: {str(e)}")
            raise

    def _load_cache(self) -> Dict:
        try:
            if os.path.exists(self.cache_file):
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache = json.load(f)
                    # Check if cache is older than 24 hours
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
                # Get more popular movies and sort by popularity
                url = f'https://api.themoviedb.org/3/movie/popular?api_key={TMDB_API_KEY}&page=1'
                response = requests.get(url, timeout=5)  # Add timeout
                response.raise_for_status()
                movies = response.json().get('results', [])
                # Sort by popularity and take top 50
                movies.sort(key=lambda x: x.get('popularity', 0), reverse=True)
                movies = movies[:50]
                self._save_cache(movies)
                return movies
            except requests.exceptions.Timeout:
                logging.error("Timeout while fetching popular movies")
                return []
            except requests.exceptions.RequestException as e:
                logging.error(f"Error fetching popular movies: {str(e)}")
                return []
            except Exception as e:
                logging.error(f"Unexpected error fetching popular movies: {str(e)}")
                return []
        return self.cache['movies']

    def _get_movie_details(self, movie_id: int) -> Dict:
        try:
            url = f'https://api.themoviedb.org/3/movie/{movie_id}?api_key={TMDB_API_KEY}&append_to_response=external_ids'
            response = requests.get(url, timeout=5)  # Add timeout
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            logging.error(f"Timeout while fetching movie details for ID {movie_id}")
            return {}
        except requests.exceptions.RequestException as e:
            logging.error(f"Error fetching movie details for ID {movie_id}: {str(e)}")
            return {}
        except Exception as e:
            logging.error(f"Unexpected error fetching movie details for ID {movie_id}: {str(e)}")
            return {}

    def query(self, query: str) -> List[Dict[str, Any]]:
        try:
            if not query or query.isspace():
                return [{
                    "Title": "Enter a movie name",
                    "SubTitle": "Type a movie name after 'tmdb' to search",
                    "IcoPath": "icon.png"
                }]

            query = query.lower()
            items = []
            popular_movies = self._get_popular_movies()

            # First, find exact matches in popular movies
            exact_matches = []
            for movie in popular_movies:
                if movie['title'].lower() == query:
                    exact_matches.append(movie)

            # Then find starts-with matches in popular movies
            start_matches = []
            for movie in popular_movies:
                if movie['title'].lower().startswith(query) and movie not in exact_matches:
                    start_matches.append(movie)

            # Then find contains matches in popular movies
            contains_matches = []
            for movie in popular_movies:
                if query in movie['title'].lower() and movie not in exact_matches and movie not in start_matches:
                    contains_matches.append(movie)

            # Combine all matches in order of priority
            all_matches = exact_matches + start_matches + contains_matches

            # Add matches to items
            for movie in all_matches[:5]:
                items.append(self._format_movie_item(movie))

            # If we don't have enough matches, search TMDB
            if len(items) < 5:
                try:
                    search_url = f'https://api.themoviedb.org/3/search/movie?api_key={TMDB_API_KEY}&query={query}&page=1'
                    response = requests.get(search_url, timeout=5)  # Add timeout
                    response.raise_for_status()
                    results = response.json().get('results', [])

                    # Filter out movies we already have
                    existing_ids = {movie['id'] for movie in all_matches}
                    new_results = [movie for movie in results if movie['id'] not in existing_ids]

                    # Add new results
                    for movie in new_results:
                        if len(items) >= 5:
                            break
                        items.append(self._format_movie_item(movie))

                except requests.exceptions.Timeout:
                    logging.error("Timeout while searching TMDB")
                    if not items:
                        return [{
                            "Title": "Search Timeout",
                            "SubTitle": "The search took too long. Please try again.",
                            "IcoPath": "icon.png"
                        }]
                except requests.exceptions.RequestException as e:
                    logging.error(f"Error searching TMDB: {str(e)}")
                    if not items:
                        return [{
                            "Title": "Network Error",
                            "SubTitle": f"Failed to connect to TMDB API: {str(e)}",
                            "IcoPath": "icon.png"
                        }]
                except Exception as e:
                    logging.error(f"Unexpected error searching TMDB: {str(e)}")
                    if not items:
                        return [{
                            "Title": "Error",
                            "SubTitle": "An unexpected error occurred. Check the log file for details.",
                            "IcoPath": "icon.png"
                        }]

            if not items:
                return [{
                    "Title": "No movies found",
                    "SubTitle": f"No results found for '{query}'",
                    "IcoPath": "icon.png"
                }]

            return items
        except Exception as e:
            logging.error(f"Unexpected error in query: {str(e)}")
            return [{
                "Title": "Error",
                "SubTitle": "An unexpected error occurred. Check the log file for details.",
                "IcoPath": "icon.png"
            }]

    def _format_movie_item(self, movie: Dict) -> Dict[str, Any]:
        try:
            title = movie.get('title', 'No Title')
            rating = movie.get('vote_average', 'N/A')
            overview = movie.get('overview', 'No overview available.')
            release_date = movie.get('release_date', 'N/A')
            movie_id = movie.get('id')
            poster_path = movie.get('poster_path')
            
            # Get poster URL
            if poster_path:
                ico_path = f"{TMDB_IMAGE_BASE_URL}/{poster_path.lstrip('/')}"
            else:
                ico_path = "icon.png"
            
            # Format the display
            year = release_date.split('-')[0] if release_date != 'N/A' else ''
            display_title = f"{title} ({year})" if year else title
            
            return {
                "Title": f"{display_title} - ⭐ {rating}/10",
                "SubTitle": overview[:150] + "..." if len(overview) > 150 else overview,
                "IcoPath": ico_path,
                "JsonRPCAction": {
                    "method": "open_movie",
                    "parameters": [movie_id],
                    "dontHideAfterAction": False
                }
            }
        except Exception as e:
            logging.error(f"Error formatting movie item: {str(e)}")
            return {
                "Title": "Error formatting result",
                "SubTitle": "There was an error displaying this movie",
                "IcoPath": "icon.png"
            }

    def open_movie(self, movie_id: int) -> None:
        try:
            movie_details = self._get_movie_details(movie_id)
            imdb_id = movie_details.get('external_ids', {}).get('imdb_id', '')
            if imdb_id:
                webbrowser.open(f"https://www.imdb.com/title/{imdb_id}")
            else:
                logging.warning(f"No IMDB ID found for movie {movie_id}")
        except Exception as e:
            logging.error(f"Error opening movie {movie_id}: {str(e)}")

if __name__ == "__main__":
    try:
        TMDBMovieSearch()
    except Exception as e:
        logging.critical(f"Critical error in plugin: {str(e)}")
        print(json.dumps({
            "result": [{
                "Title": "Critical Error",
                "SubTitle": "The plugin encountered a critical error. Check the log file for details.",
                "IcoPath": "icon.png"
            }]
        }))
