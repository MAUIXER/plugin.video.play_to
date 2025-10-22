# -*- coding: utf-8 -*-


# ========================================================================= #
#
#   Module:  prehrajto
#   Author:  Mau!X ER
#   Created on:  20.10.2025
#   License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
# ========================================================================= #



import xbmc
import xbmcgui
import xbmcplugin

import re
import ast
import json

from bs4 import BeautifulSoup
from urllib.parse import quote, urlparse


from resources.lib.utils import get_url, log, clean_title_for_tmdb, convert_size_to_bytes, duration_to_seconds




class PrehrajTo:
    def __init__(self, addon, handle, session, tmdb_client):
        self.addon = addon
        self._handle = handle
        self.session = session
        self.tmdb = tmdb_client
        self.headers = {'user-agent': 'kodi/play.to'}
        self.base_url = 'https://prehraj.to'


    def get_premium_cookies(self):
        email = self.addon.getSetting('email')
        password = self.addon.getSetting('password')
        if not email or not password:
            return None

        login_data = {
            'password': password, 'email': email, '_submit': 'Přihlásit+se',
            'remember': 'on', '_do': 'login-loginForm-submit'
        }
        try:
            res = self.session.post(self.base_url + '/', login_data)
            soup = BeautifulSoup(res.content, 'html.parser')
            if soup.find('span', {'class': 'color-green'}):
                return res.cookies
        except Exception as e:
            log(f"PREHRAJTO - Chyba při přihlašování: {e}", xbmc.LOGERROR)
        return None


    def get_video_link(self, page_content):
        soup = BeautifulSoup(page_content, 'html.parser')
        pattern = re.compile(r'var sources = \[(.*?);', re.DOTALL)
        script = soup.find('script', string=pattern)
        if not script: return None, None

        file_url, subtitle_url = None, None
        try:
            sources = pattern.findall(script.string)[0]
            file_match = re.search(r'file:\s*"(.*?)"|src:\s*"(.*?)"', sources, re.DOTALL)
            file_url = file_match.group(1) or file_match.group(2)
        except:
            pass

        try:
            pattern2 = re.compile(r'var tracks = (.*?);', re.DOTALL)
            script2 = soup.find('script', string=pattern2)
            if script2:
                raw = pattern2.findall(script2.string)[0]
                data = ast.literal_eval(raw.strip())
                subtitle_url = data[0]['src']
        except:
            pass
        return file_url, subtitle_url


    def _scrape_search_page(self, url, cookies):
        videos = []
        try:
            html = self.session.get(url, cookies=cookies, headers=self.headers).content
            soup = BeautifulSoup(html, 'html.parser')
            video_links = soup.find_all('a', {'class': 'video--link'})
            for v in video_links:
                title_elem = v.find('h3', {'class': 'video__title'})
                size_elem = v.find('div', {'class': 'video__tag--size'})
                time_elem = v.find('div', {'class': 'video__tag--time'})
                if not title_elem or not v.get('href'):
                    continue

                videos.append({
                    'title': title_elem.text.strip(),
                    'link': self.base_url + v['href'],
                    'size_str': size_elem.text.strip() if size_elem else '',
                    'duration_str': time_elem.text.strip() if time_elem else ''
                })
            next_page = soup.find('a', {'title': 'Zobrazit další'})
            return videos, bool(next_page)
        except Exception as e:
            log(f"PREHRAJTO - Chyba při scrapování stránky {url}: {e}", xbmc.LOGERROR)
            return [], False


    def search_sources(self, query, cookies):
        search_pages = int(self.addon.getSetting('search_pages') or '2')
        search_ls = int(self.addon.getSetting('search_ls') or '56')
        all_videos = []
        for p in range(1, search_pages + 1):
            url = f'{self.base_url}/hledej/{quote(query)}?vp-page={p}'
            videos, has_next = self._scrape_search_page(url, cookies)
            all_videos.extend(videos)
            if not has_next or len(all_videos) >= search_ls:
                break
        return self._filter_and_sort_videos(all_videos)


    def _filter_and_sort_videos(self, videos):
    
        # --- PLAYTO : Načtení nastavení

        quality_1080p = self.addon.getSettingBool('quality_1080p')
        quality_720p = self.addon.getSettingBool('quality_720p')
        quality_480p = self.addon.getSettingBool('quality_480p')
        quality_toggle = self.addon.getSettingBool('quality_toggle')
        prefer_dubbed = self.addon.getSettingBool('prefer_dubbed')
        sort_by_size = self.addon.getSettingBool('sort_by_size')
        exclude_suffix = self.addon.getSetting('exclude_suffix').strip().lower()
        exclude_lang = self.addon.getSetting('exclude_lang').strip().lower()
        exclude_quality = self.addon.getSetting('exclude_quality').strip().lower()

        # --- PLAYTO : Filtrace

        exclude_terms = [t for t in [exclude_suffix, exclude_lang, exclude_quality] if t]
        if exclude_terms:
            videos = [v for v in videos if not any(ex in v['title'].lower() for ex in exclude_terms)]

        preferred_qualities = []
        if quality_1080p: preferred_qualities.append('1080p')
        if quality_720p: preferred_qualities.append('720p')
        if quality_480p: preferred_qualities.append('480p')
        if quality_toggle: preferred_qualities = []

        processed_videos = []
        for v in videos:
            title_lower = v['title'].lower()
            quality = ''
            if '1080p' in title_lower or 'full hd' in title_lower: quality = '1080p'
            elif '720p' in title_lower or 'hd' in title_lower: quality = '720p'
            elif '480p' in title_lower or 'sd' in title_lower: quality = '480p'

            v['quality'] = quality
            v['dub'] = bool(re.search(r'cz\s*dabing|cz-dabing|český\s*dabing', title_lower, re.IGNORECASE))
            v['bytes'] = convert_size_to_bytes(v['size_str'])

            if prefer_dubbed and not v['dub']: continue
            if preferred_qualities and v['quality'] not in preferred_qualities: continue

            processed_videos.append(v)

        # --- PLAYTO : Řazení
        
        if sort_by_size:
            processed_videos.sort(key=lambda v: v['bytes'], reverse=True)

        return processed_videos


    def find_and_list_sources(self, meta_json):
        meta = json.loads(meta_json)
        media_type = meta.get('media_type')

        search_query = f"{meta['title']} {meta.get('year', '')}"
        if media_type == 'episode':
            try:
                season_num = int(meta.get('season', 0))
                episode_num = int(meta.get('episode', 0))
                search_query = f"{meta['tv_show_title']} S{season_num:02d}E{episode_num:02d}"
            except (ValueError, TypeError):
                search_query = f"{meta['tv_show_title']} {meta['title']}"

        log(f"PREHRAJTO - Hledám zdroje pro: '{search_query}'", xbmc.LOGINFO)
        cookies = self.get_premium_cookies()
        results = self.search_sources(search_query, cookies)

        if not results:
            xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', 'SOURCES : Žádné zdroje nenalezeny', xbmcgui.NOTIFICATION_INFO, 4000)
            xbmcplugin.endOfDirectory(self._handle, succeeded=False)
            return

        show_size = self.addon.getSettingBool('show_size')
        show_duration_time = self.addon.getSettingBool('show_duration_time')

        for video in results:
            size_display = f'[LIGHT][COLOR orange][{video["size_str"]}][/LIGHT][/COLOR]  ' if show_size and video["size_str"] else ''
            duration_display = f'[LIGHT][COLOR limegreen]· {video["duration_str"] or "N/A"} ·[/LIGHT][/COLOR]' if show_duration_time else ''
            label = f'{size_display}{video["title"]} {duration_display}'.strip()

            list_item = xbmcgui.ListItem(label=label)
            list_item.setArt({'poster': meta.get('poster'), 'fanart': meta.get('fanart'), 'icon': meta.get('poster'), 'thumb': meta.get('poster')})
            list_item.setProperty('IsPlayable', 'true')

            play_url = get_url(action='play', link=video['link'], meta=json.dumps(meta))
            xbmcplugin.addDirectoryItem(handle=self._handle, url=play_url, listitem=list_item, isFolder=False)

        xbmcplugin.endOfDirectory(self._handle)
