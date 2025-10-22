# -*- coding: utf-8 -*-


##############################################################################
#
#  Module: csfd
#  Author: MauiX ER
#  Created on: 05.06.2025
#  License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################



import xbmc
import xbmcgui
import xbmcvfs
import xbmcaddon

import re
import json
import time
import random
import requests

from bs4 import BeautifulSoup
from urllib.parse import quote
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed


from resources.lib.utils import log, popinfo




BASE_URL = "https://www.csfd.cz/"
CSFD_TIPS_URL = "https://www.csfd.cz/televize/"
CSFD_ID_REGEX = r'\/film\/(\d+)-'
TIMEOUT = 30




class CSFD:
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.88 Safari/537.36',
        'Mozilla/5.0 (Linux; Android 10; SM-A205U) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.101 Mobile Safari/537.36',
    #   'Mozilla/5.0 (iPhone; CPU iPhone OS 14_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/87.0.4280.77 Mobile/15E148 Safari/604.1'
    ]

    def __init__(self, addon_obj):

        self.addon = addon_obj
        self.base_url = BASE_URL
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": random.choice(self.USER_AGENTS)})

        self.tmdb_api_key = self.addon.getSetting('api_key').strip()
        self.tmdb_base_url = "https://api.themoviedb.org/3"
        self.tmdb_poster_base_url = "https://image.tmdb.org/t/p/w780"
        self.tmdb_fanart_base_url = "https://image.tmdb.org/t/p/w1280"

        csfd_cache_path_setting = addon_obj.getSetting('csfd_cache_path')
        default_path = "special://userdata/PLAY-DATA/CACHE-CSFD"
        self.cache_dir = xbmcvfs.translatePath(csfd_cache_path_setting or default_path)
        
        if not xbmcvfs.exists(self.cache_dir):
            xbmcvfs.mkdirs(self.cache_dir)



    def _load_cache(self, cache_key: str):
        cache_file = f"{self.cache_dir}/{cache_key}.json"
        if xbmcvfs.exists(cache_file):
            try:
                with xbmcvfs.File(cache_file) as f:
                    cache_data = json.loads(f.read())
                if cache_data.get("expires", 0) > time.time():
                    log(f"CSFD - Loaded cache for {cache_key}", level=xbmc.LOGDEBUG)
                    return cache_data.get("data", {})
                else:
                    log(f"CSFD - Cache expired for {cache_key}", level=xbmc.LOGDEBUG)
                    xbmcvfs.delete(cache_file)
            except Exception as e:
                log(f"CSFD - Error loading cache for {cache_key} : {str(e)}", level=xbmc.LOGERROR)
        return None



    def _save_cache(self, cache_key: str, data, expires_in: int = 86400) -> None:
        cache_file = f"{self.cache_dir}/{cache_key}.json"
        cache_data = {
            "data": data,
            "expires": time.time() + expires_in
        }
        try:
            with xbmcvfs.File(cache_file, 'w') as f: # 'w' pro zápis
                f.write(json.dumps(cache_data, ensure_ascii=False))
            xbmc.log(f"Saved cache for {cache_key}", level=xbmc.LOGDEBUG)
        except Exception as e:
            log(f"CSFD - Error saving cache for {cache_key} : {str(e)}", level=xbmc.LOGERROR)



    def _get_tmdb_images(self, title: str, year: str) -> tuple:
        cache_key = f"tmdb_{title.lower()}_{year}_movie"
        cached_data = self._load_cache(cache_key)
        if cached_data:
            log(f"CSFD - Returning cached TMDb images for {cache_key}", level=xbmc.LOGDEBUG)
            return cached_data.get("poster"), cached_data.get("fanart")

        try:
            time.sleep(0.1)
            search_endpoint = f"{self.tmdb_base_url}/search/movie"
            params = {
                "api_key": self.tmdb_api_key,
                "query": quote(title),
                "language": "en-US",
                "year": year
            }
            response = self.session.get(search_endpoint, params=params, timeout=TIMEOUT)
            if response.status_code != 200:
                log(f"CSFD - TMDb search failed for {title} ({year}): {response.status_code}", level=xbmc.LOGERROR)
                return None, None

            data = response.json()
            if not data.get("results"):
                params_no_year = params.copy()
                params_no_year.pop("year", None)
                response = self.session.get(search_endpoint, params=params_no_year, timeout=TIMEOUT)
                data = response.json()
                if not data.get("results"):
                    log(f"CSFD - No TMDb results for {title} ({year})", level=xbmc.LOGDEBUG)
                    return None, None

            result = data["results"][0]
            poster_path = result.get("poster_path")
            backdrop_path = result.get("backdrop_path")

            poster_url = f"{self.tmdb_poster_base_url}{poster_path}" if poster_path else None
            fanart_url = f"{self.tmdb_fanart_base_url}{backdrop_path}" if backdrop_path else poster_url
            log(f"CSFD - TMDb images for {title} : poster={poster_url}, fanart={fanart_url}", level=xbmc.LOGDEBUG)

            self._save_cache(cache_key, {"poster": poster_url, "fanart": fanart_url})
            return poster_url, fanart_url
        except Exception as e:
            log(f"CSFD - Error fetching TMDb images for {title} : {str(e)}", level=xbmc.LOGERROR)
            return None, None



    def get_daily_tips(self):
        log("CSFD - Starting get_daily_tips", level=xbmc.LOGDEBUG)
        cache_key = "daily_tips"
        cached_data = self._load_cache(cache_key)
        if cached_data:
            log("CSFD - Returning cached daily tips", level=xbmc.LOGDEBUG)
            return cached_data

        url = CSFD_TIPS_URL

        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "cs-CZ,cs;q=0.8,en-US;q=0.5,en;q=0.3",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": self.base_url,
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
        cookies = {
            "cf_clearance": "",
            "PHPSESSID": "",
            "_ga": "",
            "_gid": ""
        }
        log(f"CSFD - Fetching URL: {url}", level=xbmc.LOGDEBUG)
        
        try:
            response = self.session.get(url, headers=headers, cookies=cookies, timeout=TIMEOUT)
            xbmc.log(f"Response status code: {response.status_code}", level=xbmc.LOGDEBUG)
            if 600 > response.status_code >= 400:
                log(f"CSFD - Failed to get daily tips. Status code : {response.status_code}", level=xbmc.LOGERROR)
                return []
            
            soup = BeautifulSoup(response.text.encode('utf-8'), "html.parser")
            log("CSFD - HTML parsed successfully", level=xbmc.LOGDEBUG)
            
            tips = []
            tips_section = None
            selectors = [
                ('section', {'id': 'tv-tip'}),
                ('div', {'class': 'box box-tv-tip'}),
                ('div', {'class': 'tv-tips-container'}),
                ('div', {'class': 'tv-tip-box'}),
                ('section', {'class': 'tv-tips'}),
                ('div', {'class': 'box-content tv-tips'}),
                ('div', {'class': lambda x: x and ('tip' in x.lower() or 'tv' in x.lower())}),
                ('section', {'class': lambda x: x and ('tip' in x.lower() or 'tv' in x.lower())})
            ]
            for tag, attrs in selectors:
                tips_section = soup.find(tag, attrs)
                if tips_section:
                    log(f"CSFD - Found tips section with selector : {tag} {attrs}", level=xbmc.LOGDEBUG)
                    break
            
            if not tips_section:
                log("CSFD - No TV tips section found.", level=xbmc.LOGWARNING)
                return tips
            
            article_selectors = [
                ('article', {'class': 'article'}),
                ('div', {'class': 'tip-item'}),
                ('li', {'class': 'tv-tip-item'}),
                ('div', {'class': 'film-item'}),
                ('div', {'class': lambda x: x and ('item' in x.lower() or 'tip' in x.lower())}),
                ('li', {'class': lambda x: x and ('item' in x.lower() or 'tip' in x.lower())})
            ]
            articles = []
            for tag, attrs in article_selectors:
                articles = tips_section.find_all(tag, attrs)
                if articles:
                    log(f"CSFD - Found {len(articles)} articles with selector : {tag} {attrs}", level=xbmc.LOGDEBUG)
                    break
            
            if not articles:
                log("CSFD - No articles found in TV tips section.", level=xbmc.LOGWARNING)
                return tips
            
            tip_ids = []
            for article in articles:
                title_elem = article.find('a', class_='film-title-name')
                if not title_elem:
                    log("CSFD - No title element found in article.", level=xbmc.LOGDEBUG)
                    continue
                href = title_elem.get('href', '')
                full_id = re.search(CSFD_ID_REGEX, href)
                if not full_id:
                    log("CSFD - Failed to extract full_id from href.", level=xbmc.LOGDEBUG)
                    continue
                full_id = full_id.group(1)
                
                tip_type = "movie"
                
                time_channel_elem = article.find('span', class_='tv-tip-time')
                time = None
                channel = None
                if time_channel_elem:
                    time_text = time_channel_elem.text.strip()
                    time_match = re.search(r'(\d{1,2}:\d{2})', time_text)
                    if time_match:
                        time = time_match.group(1)
                    channel_elem = time_channel_elem.find('img') or time_channel_elem.find('span', class_=lambda x: x and 'channel' in x.lower())
                    if channel_elem and 'alt' in channel_elem.attrs:
                        channel = channel_elem['alt'].strip()
                    elif channel_elem:
                        channel = channel_elem.text.strip()
                
                tip_ids.append({
                    'id': full_id,
                    'type': tip_type,
                    'time': time,
                    'channel': channel
                })
            
            with ThreadPoolExecutor(max_workers=3) as executor:
                future_to_id = {executor.submit(self.get_detail, tip['id']): tip for tip in tip_ids}
                for future in as_completed(future_to_id):
                    tip = future_to_id[future]
                    try:
                        details = future.result()
                        if not details or not details.get('title'):
                            log(f"CSFD - Invalid details for {tip['id']}", level=xbmc.LOGWARNING)
                            continue
                        details.update({
                            'id': tip['id'],
                            'time': tip['time'],
                            'channel': tip['channel'],
                            'type': tip['type']
                        })
                        tips.append(details)
                    except Exception as e:
                        log(f"CSFD - Failed to get details for {tip['id']}: {str(e)}", level=xbmc.LOGERROR)
            
            log(f"CSFD - Returning {len(tips)} tips.", level=xbmc.LOGDEBUG)
            self._save_cache(cache_key, tips)
            return tips
        except Exception as e:
            log(f"CSFD - Error fetching daily tips: {str(e)}", level=xbmc.LOGERROR)
            return []



    def get_detail(self, full_id):
        cache_key = f"detail_{full_id}"
        cached_data = self._load_cache(cache_key)
        if cached_data:
            log(f"CSFD - Returning cached details for {full_id}", level=xbmc.LOGDEBUG)
            return cached_data

        log(f"CSFD - Fetching details for ID : {full_id}", level=xbmc.LOGDEBUG)
        url = f"{self.base_url}film/{full_id}/prehled"
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
        }
        
        try:
            response = self.session.get(url, headers=headers, timeout=TIMEOUT)
            if 600 > response.status_code >= 400:
                log(f"CSFD - Failed to get detail for {full_id}. Status code: {response.status_code}", level=xbmc.LOGERROR)
                return {}
            
            soup = BeautifulSoup(response.text.encode('utf-8'), "html.parser")
            log(f"CSFD - HTML parsed for {url}", level=xbmc.LOGDEBUG)

            title = None
            title_elem = soup.find('h1')
            if title_elem:
                title = title_elem.text.strip()

            year = None
            origin_elem = soup.find('div', {'class': 'origin'})
            if origin_elem:
                year_match = re.search(r'(\d{4})', origin_elem.text)
                if year_match:
                    year = year_match.group(1)

            rating = None
            rating_elem = soup.find('div', {'class': 'film-rating-average'})
            if rating_elem:
                rating = rating_elem.text.strip()

            genres = []
            genres_elem = soup.find('div', {'class': 'genres'})
            if genres_elem:
                genre_links = genres_elem.find_all('a')
                genres = [g.text.strip() for g in genre_links]

            plot = None
            plot_elem = soup.find('div', {'class': 'plot-full'})
            if plot_elem:
                plot = plot_elem.get_text().strip().split('\n')[0]

            original_title = None
            if origin_elem and 'Česko' not in origin_elem.text:
                film_names = soup.find('ul', {'class': 'film-names'})
                if film_names:
                    first_name = film_names.find('li')
                    if first_name:
                        original_title = first_name.text.strip()

            poster = None
            fanart = None

            log(f"CSFD - Fetching TMDb images for {title or 'Unknown'} ({year or ''})", level=xbmc.LOGDEBUG)

            # --- Use title + year as the primary search query
            if title and year:
                poster, fanart = self._get_tmdb_images(title, year)

            # --- Fallback to title without year if no results
            if not poster and title:
                poster, fanart = self._get_tmdb_images(title, "")

            # --- Fallback to original_title + year if still no results
            if not poster and original_title and original_title != title and year:
                poster, fanart = self._get_tmdb_images(original_title, year)

            # --- Final fallback to original_title without year
            if not poster and original_title and original_title != title:
                poster, fanart = self._get_tmdb_images(original_title, "")


            if not poster:
                poster = "https://static.wikitide.net/allthetropeswiki/6/6e/Ahitler.jpg"
                fanart = "https://static.wikitide.net/allthetropeswiki/6/6e/Ahitler.jpg"
                log(f"CSFD - Using placeholder images for {title or original_title or 'Unknown'}", level=xbmc.LOGWARNING)


            details = {
                'title': title,
                'original_title': original_title,
                'year': year,
                'rating': rating,
                'genres': genres,
                'plot': plot,
                'poster': poster,
                'fanart': fanart
            }

            self._save_cache(cache_key, details)
            log(f"CSFD - Cached details for {full_id}", level=xbmc.LOGDEBUG)
            return details
        except Exception as e:
            log(f"CSFD - Error fetching details for {full_id}: {str(e)}", level=xbmc.LOGERROR)
            return {}




if __name__ == "__main__":

    # --- MOCK TESTS : Pro testování mimo Kodi je potřeba mock addon objekt

    class MockAddon:
        def getSetting(self, id): return ""
    csfd = CSFD(MockAddon())
    print(json.dumps(csfd.get_daily_tips(), indent=2, ensure_ascii=False))
