# -*- coding: utf-8 -*-


##############################################################################
#
#  Module: series_manager
#  Author: MauiX ER
#  Created on: 22.05.2025
#  License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
##############################################################################



import xbmc
import xbmcgui
import xbmcvfs

import os
import io
import re
import json
import time
import requests

from bs4 import BeautifulSoup
from urllib.parse import quote, urlencode, parse_qsl


from resources.lib.utils import log, popinfo, safe_get




EPISODE_PATTERNS = [
    r'[Ss](\d+)[Ee](\d+)',  # S01E01 format
    r'(\d+)x(\d+)',         # 1x01 format
    r'[Ee]pisode\s*(\d+)',  # Episode 1 format
    r'[Ee]p\s*(\d+)',       # Ep 1 format
    r'[Ee](\d+)',           # E1 format
    r'(\d+)\.\s*(\d+)'      # 1.01 format
]




headers = {'user-agent': 'kodi/prehraj.to'}




class SeriesManager:
    def __init__(self, addon, profile):
        self.addon = addon

        series_db_setting = self.addon.getSetting('series_db')
        watched_db_setting = self.addon.getSetting('watched_db')
        default_series_db_path = "special://userdata/Database/PLAY-BASE/TV-SERIES"
        default_watched_db_path = "special://userdata/Database/PLAY-BASE/TV-WATCHED"

        self.series_db_path = xbmcvfs.translatePath(series_db_setting or default_series_db_path)
        self.watched_db_path = xbmcvfs.translatePath(watched_db_setting or default_watched_db_path)
        self.ensure_db_exists()


    def ensure_db_exists(self):
        """Zajistí existenci adresářů pro databázi seriálů a zhlédnutí."""
        try:
            for path in [self.series_db_path, self.watched_db_path]:
                if not xbmcvfs.exists(path):
                    log(f'TV-MANAGER - Vytvářím adresář : {path}', level=xbmc.LOGINFO) # Přidáno logování
                    xbmcvfs.mkdirs(path)
        except Exception as e:
            log(f'TV-MANAGER - Chyba při vytváření adresářů : {str(e)}', level=xbmc.LOGERROR)


    def search_series(self, series_name, cookies=None):
        series_name_upper = series_name.upper()       # --- Uložení názvu velkými písmeny
        series_data = {
            'name': series_name_upper,
            'last_updated': xbmc.getInfoLabel('System.Date'),
            'seasons': {}
        }

        search_queries = [
            series_name,
            f"{series_name} season",
            f"{series_name} s01",
            f"{series_name} episode"
        ]

        all_results = []
        for query in search_queries:
            results = self._perform_search(query, cookies)
            for result in results:
                if result not in all_results and self._is_likely_episode(result['name'], series_name):
                    quality = self._detect_quality(result['name'])
                    if quality not in ['4k', '2160p']:
                        all_results.append({**result, 'quality': quality})

        # --- Seřazení výsledků podle kvality (1080p první, pak 720p, 480p, neznámá)

        quality_priority = {'1080p': 1, '720p': 2, '480p': 3, 'unknown': 4}
        all_results.sort(key=lambda x: quality_priority.get(x['quality'], 4))

        for item in all_results:
            season_num, episode_num = self._detect_episode_info(item['name'], series_name)
            if season_num is not None:
                season_num_str = str(season_num)
                episode_num_str = str(episode_num)

                if season_num_str not in series_data['seasons']:
                    series_data['seasons'][season_num_str] = {}

                series_data['seasons'][season_num_str][episode_num_str] = {
                    'name': item['name'],
                    'ident': item['ident'],
                    'size': item.get('size', '0'),
                    'added_timestamp': time.time(),
                    'quality': item['quality']
                }

        self._save_series_data(series_name, series_data)
        return series_data


    def _detect_quality(self, filename):
        filename_lower = filename.lower()
        if '1080p' in filename_lower or 'full hd' in filename_lower:
            return '1080p'
        elif '720p' in filename_lower:
            return '720p'
        elif '480p' in filename_lower:
            return '480p'
        return 'unknown'


    def _is_likely_episode(self, filename, series_name):
        if not re.search(re.escape(series_name), filename, re.IGNORECASE):
            return False

        for pattern in EPISODE_PATTERNS:
            if re.search(pattern, filename, re.IGNORECASE):
                return True

        episode_keywords = [
            'episode', 'season', 'series', 'ep', 
            'complete', 'serie', 'season', 'disk'
        ]

        for keyword in episode_keywords:
            if keyword in filename.lower():
                return True

        return False


    def _perform_search(self, search_query, cookies):
        results = []
        p = 1
        max_pages = 5   # --- Limit to prevent excessive scraping
        try:
            while p <= max_pages:
                url = f'https://prehraj.to:443/hledej/{quote(search_query)}?vp-page={p}'
                # add timeout to prevent blocking the main thread
                resp = safe_get(url, cookies=cookies, headers=headers, timeout=15)
                content = resp.content if resp is not None else b''
                soup = BeautifulSoup(content, 'html.parser')
                video_links = soup.find_all('a', {'class': 'video--link'})
                for v in video_links:
                    name = v.find('h3', {'class': 'video__title'}).text.strip() if v.find('h3') else ''
                    ident = v['href']  # Full path like '/video/ident'
                    size_elem = v.find('div', {'class': 'video__tag--size'})
                    size = size_elem.text.strip() if size_elem else '0'
                    if name and ident:
                        results.append({'name': name, 'ident': ident, 'size': size})
                next_page = soup.find('a', {'title': 'Zobrazit další'})
                if not next_page:
                    break
                p += 1
        except requests.exceptions.RequestException as e:
            log(f'TV-MANAGER - Network error during server search : {str(e)}', level=xbmc.LOGERROR)
        except Exception as e:
            log(f'TV-MANAGER - Server search error : {str(e)}', level=xbmc.LOGERROR)
        return results


    def _detect_episode_info(self, filename, series_name):
        cleaned = filename.lower().replace(series_name.lower(), '').strip()

        for pattern in EPISODE_PATTERNS:
            match = re.search(pattern, cleaned)
            if match:
                groups = match.groups()
                if len(groups) == 2:
                    return int(groups[0]), int(groups[1])
                elif len(groups) == 1:
                    return 1, int(groups[0])

        if 'season' in cleaned.lower() or 'serie' in cleaned.lower():
            season_match = re.search(r'season\s*(\d+)', cleaned.lower())
            if season_match:
                season_num = int(season_match.group(1))
                ep_match = re.search(r'(\d+)', cleaned.replace(season_match.group(0), ''))
                if ep_match:
                    return season_num, int(ep_match.group(1))

        return None, None


    def _save_series_data(self, series_name, series_data):
        safe_name = self._safe_filename(series_name)
        file_path = os.path.join(self.series_db_path, f"{safe_name}.json")

        try:
            with xbmcvfs.File(file_path, 'w') as f:
                data = json.dumps(series_data, indent=2, ensure_ascii=False)
                f.write(data)
        except Exception as e:
            log(f'TV-MANAGER - Error saving series data : {str(e)}', level=xbmc.LOGERROR)


    def load_series_data(self, series_name):
        safe_name = self._safe_filename(series_name)
        file_path = os.path.join(self.series_db_path, f"{safe_name}.json")

        if not xbmcvfs.exists(file_path):
            return None

        try:
            with xbmcvfs.File(file_path, 'r') as f:
                data = f.read()
                series_data = json.loads(data)
                return series_data
        except Exception as e:
            log(f'TV-MANAGER - Error loading series data : {str(e)}', level=xbmc.LOGERROR)
            return None


    def get_all_series(self):
        series_list = []

        try:
            files = xbmcvfs.listdir(self.series_db_path)[1]  # Get files only
            for filename in files:
                if filename.endswith('.json'):
                    series_name = os.path.splitext(filename)[0]
                    proper_name = series_name.replace('_', ' ')
                    series_list.append({
                        'name': proper_name.upper(),    # --- Zobrazení názvu velkými písmeny
                        'filename': filename,
                        'safe_name': series_name
                    })
        except Exception as e:
            log(f'TV-MANAGER - Error listing series : {str(e)}', level=xbmc.LOGERROR)

        return series_list


    def _safe_filename(self, name):
        safe = re.sub(r'[^\w\-_\. ]', '_', name)
        return safe.lower().replace(' ', '_')


    def delete_episode(self, series_name, season_num, episode_num):
        series_data = self.load_series_data(series_name)
        if not series_data or str(season_num) not in series_data['seasons']:
            return False

        season_num = str(season_num)
        episode_num = str(episode_num)

        if episode_num in series_data['seasons'][season_num]:
            del series_data['seasons'][season_num][episode_num]

            if not series_data['seasons'][season_num]:
                del series_data['seasons'][season_num]

            if not series_data['seasons']:
                safe_name = self._safe_filename(series_name)
                file_path = os.path.join(self.series_db_path, f"{safe_name}.json")
                if xbmcvfs.exists(file_path):
                    xbmcvfs.delete(file_path)
            else:
                self._save_series_data(series_name, series_data)

            return True
        return False


    def delete_season(self, series_name, season_num):
        series_data = self.load_series_data(series_name)
        if not series_data or str(season_num) not in series_data['seasons']:
            return False

        season_num = str(season_num)
        del series_data['seasons'][season_num]

        if not series_data['seasons']:
            safe_name = self._safe_filename(series_name)
            file_path = os.path.join(self.series_db_path, f"{safe_name}.json")
            if xbmcvfs.exists(file_path):
                xbmcvfs.delete(file_path)
        else:
            self._save_series_data(series_name, series_data)

        return True


    def delete_series(self, series_name):
        safe_name = self._safe_filename(series_name)
        series_file_path = os.path.join(self.series_db_path, f"{safe_name}.json")
        watched_file_path = os.path.join(self.watched_db_path, f"{safe_name}.json")
        
        success_series = False
        success_watched = True

        if xbmcvfs.exists(series_file_path):
            try:
                xbmcvfs.delete(series_file_path)
                log(f'TV-MANAGER - Smazán seriál : {series_file_path}', level=xbmc.LOGINFO)
                success_series = True
            except Exception as e:
                log(f'TV-MANAGER - Chyba při mazání souboru seriálu : {str(e)}', level=xbmc.LOGERROR)
        else:
             success_series = True

        if xbmcvfs.exists(watched_file_path):
            try:
                xbmcvfs.delete(watched_file_path)
                log(f'TV-MANAGER - Smazána zhlédnutá data pro seriál : {watched_file_path}', level=xbmc.LOGINFO)
            except Exception as e:
                log(f'TV-MANAGER - Chyba při mazání zhlédnutých dat : {str(e)}', level=xbmc.LOGERROR)
                success_watched = False

        return success_series and success_watched


    def mark_episode_watched(self, series_name, season_num, episode_num):
        watched_data = self._load_watched_data(series_name)
        if not watched_data:
            watched_data = {'series_name': series_name.upper(), 'watched': {}}

        season_num = str(season_num)
        episode_num = str(episode_num)

        if season_num not in watched_data['watched']:
            watched_data['watched'][season_num] = {}

        watched_data['watched'][season_num][episode_num] = {
            'watched_timestamp': time.time(),
            'watched': True
        }

        self._save_watched_data(series_name, watched_data)
        return True


    def is_episode_watched(self, series_name, season_num, episode_num):
        watched_data = self._load_watched_data(series_name)
        season_num = str(season_num)
        episode_num = str(episode_num)

        return (watched_data and 
                season_num in watched_data['watched'] and 
                episode_num in watched_data['watched'][season_num] and
                watched_data['watched'][season_num][episode_num]['watched'])


    def _save_watched_data(self, series_name, watched_data):
        safe_name = self._safe_filename(series_name)
        file_path = os.path.join(self.watched_db_path, f"{safe_name}.json")

        try:
            with xbmcvfs.File(file_path, 'w') as f:
                data = json.dumps(watched_data, indent=2, ensure_ascii=False)
                f.write(data)
        except Exception as e:
            log(f'TV-MANAGER - Chyba při ukládání dat zhlédnutí : {str(e)}', level=xbmc.LOGERROR)


    def _load_watched_data(self, series_name):
        safe_name = self._safe_filename(series_name)
        file_path = os.path.join(self.watched_db_path, f"{safe_name}.json")

        if not xbmcvfs.exists(file_path):
            return None

        try:
            with xbmcvfs.File(file_path, 'r') as f:
                data = f.read()
                watched_data = json.loads(data)
                return watched_data
        except Exception as e:
            log(f'TV-MANAGER - Chyba při načítání dat zhlédnutí : {str(e)}', level=xbmc.LOGERROR)
            return None


    def mark_episode_unwatched(self, series_name, season_num, episode_num):
        watched_data = self._load_watched_data(series_name)
        if not watched_data or 'watched' not in watched_data:
        
             # --- Pokud epizoda není označena jako zhlédnutá, není třeba nic dělat
             
            return True

        season_num = str(season_num)
        episode_num = str(episode_num)

        if (season_num in watched_data['watched'] and 
                episode_num in watched_data['watched'][season_num]):
            del watched_data['watched'][season_num][episode_num]

            # --- Odstranění prázdné sezóny, pokud neobsahuje žádné zhlédnuté epizody
            
            if not watched_data['watched'][season_num]:
                del watched_data['watched'][season_num]

            # --- Uložení aktualizovaných dat
            
            self._save_watched_data(series_name, watched_data)
            
            return True
            
        # --- Epizoda nebyla označena jako zhlédnutá, takže není co měnit
        
        return True  
