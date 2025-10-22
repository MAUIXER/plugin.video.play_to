# -*- coding: utf-8 -*-


# ========================================================================= #
#
#   Module:  tmdb
#   Author:  Mau!X ER
#   Created on:  20.10.2025
#   License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
# ========================================================================= #



import xbmc
import xbmcgui
import xbmcvfs
import xbmcplugin

import json
import datetime


from resources.lib import tmdb_account
from resources.lib.utils import get_url, log, popinfo




class TMDB:
    def __init__(self, addon, handle, session, load_cache_func, save_cache_func):

        self.addon = addon
        self._handle = handle
        self.session = session
        self.load_cache = load_cache_func
        self.save_cache = save_cache_func

        self.api_key = self.addon.getSetting('api_key').strip()


        # ========================================================================================================
        # self.language = self.addon.getSetting('tmdb_language') or 'cs_CZ'
        # self.language = (self.addon.getSetting('tmdb_language') or 'cs_CZ').replace('_', '-')

        lang_setting = self.addon.getSetting('tmdb_language')  # --- LANG : SETTINGS.XML

        if lang_setting == 'auto':
            kodi_lang = xbmc.getLanguage(xbmc.ISO_639_1) or 'en'  # 2-letter Kodi GUI code
            # map common codes to TMDB locales
            lang_map = {
                'cs': 'cs-CZ',
                'sk': 'sk-SK',
                'en': 'en-US',
                'de': 'de-DE',
                'fr': 'fr-FR',
                'pl': 'pl-PL',
                'es': 'es-ES',
                'it': 'it-IT'
            }
            self.language = lang_map.get(kodi_lang, f"{kodi_lang}-{kodi_lang.upper()}")
        else:
            self.language = lang_setting.replace('_', '-')

        log(f"TMDB FETCH  : L A N G U A G E :  INICIALIZACE - JAZYK NASTAVEN NA  '{self.language}'", xbmc.LOGINFO)
        # ========================================================================================================


        self.show_tmdb_rating = self.addon.getSettingBool('show_tmdb_rating')
        self.enable_trakt_context = self.addon.getSettingBool('enable_trakt_context')

        self.base_url = "https://api.themoviedb.org/3"
        self.image_base_url = "https://image.tmdb.org/t/p/"




    def _fetch(self, endpoint, params=None, cache_key=None):
        if not self.api_key:
            log("TMDB - FETCH Chybí TMDB API klíč v nastavení !", xbmc.LOGERROR)
            xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', 'TMDB FETCH : Chybí TMDB API klíč v nastavení !', xbmcgui.NOTIFICATION_ERROR, 4000)
            return None

        if cache_key:
            cached_data = self.load_cache(cache_key)
            if cached_data is not None:
                log(f"TMDB - FETCH CACHE Používám cachovaná data pro '{cache_key}' (TMDB FETCH)", xbmc.LOGINFO)
                return cached_data


        #########################################################################################################
        ####################################      VIETCONG FILTER      ##########################################


        params = params or {}
        params['api_key'] = self.api_key

        # =====================================================
        # params['language'] = self.language.replace('_', '-')

        params['language'] = self.language
        # =====================================================

        url = f"{self.base_url}/{endpoint}"
        log(f"TMDB - FETCH  : L A N G U A G E :  TMDB API  {url}  with params :  {params}", xbmc.LOGDEBUG)


        ####################################      VIETCONG FILTER      ##########################################


        try:
            response = self.session.get(url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()

            # --- FETCH : Filtrování asijského obsahu  ( po načtení dat )

            if isinstance(data, dict) and "results" in data:
                import re

                allowed_langs = {"en", "cs", "sk", "de", "fr", "pl", "es", "it"}
                asian_pattern = re.compile(r'[\u3040-\u30ff\u4e00-\u9fff\uac00-\ud7af]')

                before = len(data["results"])
                filtered = []

                for item in data["results"]:
                    lang = item.get("original_language", "")
                    title = (item.get("title") or item.get("name") or item.get("original_title") or "").strip()

                    # --- FETCH : Přeskoč asijské jazyky nebo znaky v názvu

                    if lang not in allowed_langs:
                        continue
                    if asian_pattern.search(title):
                        continue

                    filtered.append(item)

                after = len(filtered)
                if before != after:
                    log(f"TMDB FETCH  : L A N G U A G E :  FILTER ODSTRANIL  {before - after}  POLOŽEK Z  {before}", xbmc.LOGINFO)
                    for item in filtered[:5]:
                       log(f"TMDB FETCH  : L A N G U A G E :  FILTER ZACHOVAL  {item.get('title', item.get('name', item.get('original_title')))} | lang={item.get('original_language')}", xbmc.LOGDEBUG)


        ####################################      VIETCONG FILTER      ##########################################
        #########################################################################################################


                data["results"] = filtered

            if cache_key:
                self.save_cache(cache_key, data)

            return data

        except Exception as e:
            log(f"TMDB - FETCH Neočekávaná chyba : {str(e)}", xbmc.LOGERROR)
            xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', f'FETCH : Chyba TMDB API : {e}', xbmcgui.NOTIFICATION_ERROR, 4000)
            return None




    def get_genres(self, media_type):
        cache_key = f"genres_{media_type}"
        cached_genres = self.load_cache(cache_key)
        if cached_genres is not None:
            return cached_genres

        endpoint = f"genre/{media_type}/list"
        data = self._fetch(endpoint, cache_key=cache_key)
        if not data or 'genres' not in data:
            return {}

        genres_dict = {g['id']: g['name'] for g in data.get('genres', [])}
        if genres_dict:
            self.save_cache(cache_key, genres_dict)
        return genres_dict



    def list_items(self, data, media_type, page, action_name, context_type='general'):
        results = data.get('results', [])
        total_pages = data.get('total_pages', 1)

        if media_type == 'multi':
            genres_movie_dict = self.get_genres('movie')
            genres_tv_dict = self.get_genres('tv')
        else:
            genres_dict = self.get_genres(media_type)

        for r in results:
            item_media_type = r.get('media_type', media_type)
            if item_media_type not in ['movie', 'tv']:
                continue
            if media_type == 'multi':
                genres_dict = genres_movie_dict if item_media_type == 'movie' else genres_tv_dict

            tmdb_id = r.get('id')
            title = r.get('title') or r.get('name') or r.get('original_title') or r.get('original_name')
            original_title = r.get('original_title') or r.get('original_name') or title

            log(f"TMDB - ITEMS  : L A N G U A G E :  {title} | original_title={original_title} | lang={r.get('original_language')}", xbmc.LOGDEBUG)

            year = (r.get('release_date', '')[:4] or r.get('first_air_date', '')[:4])
            plot = r.get('overview', '')
            rating = r.get('vote_average', 0.0)
            poster_path = r.get('poster_path')
            backdrop_path = r.get('backdrop_path')
            genre_ids = r.get('genre_ids', [])
            genres = [genres_dict.get(i, '') for i in genre_ids]
            poster = f"{self.image_base_url}w500{poster_path}" if poster_path else ''
            fanart = f"{self.image_base_url}original{backdrop_path}" if backdrop_path else ''

            list_item = xbmcgui.ListItem(label=f"{title} ({year})")
            info_tag = list_item.getVideoInfoTag()
            info_tag.setMediaType(item_media_type)
            info_tag.setTitle(title)
            info_tag.setOriginalTitle(original_title)
            info_tag.setYear(int(year) if year.isdigit() else 0)
            info_tag.setPlot(plot)
            info_tag.setGenres(genres)
            if self.show_tmdb_rating:
                info_tag.setRating(float(rating))
            info_tag.setDbId(tmdb_id)

            list_item.setArt({'poster': poster, 'thumb': poster, 'fanart': fanart, 'icon': poster})

            context_menu_items = self._build_context_menu(tmdb_id, item_media_type, title, context_type)
            list_item.addContextMenuItems(context_menu_items, replaceItems=False)

            meta = {
                'tmdb_id': tmdb_id, 'title': title, 'original_title': original_title, 'year': year,
                'plot': plot, 'poster': poster, 'fanart': fanart, 'rating': rating,
                'genres': genres, 'media_type': item_media_type
            }

            is_folder = True
            if item_media_type == 'movie':
                url = get_url(action='find_sources', meta=json.dumps(meta))
            else:
                url = get_url(action='listing_tmdb_tv', tmdb_id=str(tmdb_id), meta=json.dumps(meta))

            xbmcplugin.addDirectoryItem(self._handle, url, list_item, isFolder=is_folder)

        if int(page) < total_pages:
            next_page_item = xbmcgui.ListItem(label='[COLOR orange]| DALŠÍ STRANA ==>[/COLOR]')
            next_page_url = get_url(action=action_name, type=media_type, page=str(int(page) + 1))
            xbmcplugin.addDirectoryItem(self._handle, next_page_url, next_page_item, isFolder=True)

        content_type = 'movies' if media_type == 'movie' else 'tvshows'
        xbmcplugin.setContent(self._handle, content_type)
        xbmcplugin.endOfDirectory(self._handle)



    def _build_context_menu(self, tmdb_id, media_type, title, context_type='general'):


        from resources.lib import trakt


        context_menu_items = [
            ('[COLOR orange]PLAY : [/COLOR]VYHLEDAT TITUL', f"RunPlugin({get_url(action='search_title', name=title)})")
        ]

        if context_type == 'watchlist':
            context_menu_items.append(
                ('[COLOR red]TMDB : [/COLOR]ODEBRAT POLOŽKU', f"RunPlugin({get_url(action='tmdb_remove_watchlist', tmdb_id=tmdb_id, media_type=media_type)})")
            )
        elif context_type == 'favorites':
            context_menu_items.append(
                ('[COLOR red]TMDB : [/COLOR]ODEBRAT POLOŽKU', f"RunPlugin({get_url(action='tmdb_remove_favorite', tmdb_id=tmdb_id, media_type=media_type)})")
            )
        elif context_type == 'rated':
            context_menu_items.append(
                ('[COLOR red]TMDB : [/COLOR]ODEBRAT HODNOCENÍ', f"RunPlugin({get_url(action='tmdb_remove_rating', tmdb_id=tmdb_id, media_type=media_type)})")
            )

        # --- CONTEXT : GENERAL TMDB MENU

        else:
            context_menu_items.extend([
                ('[COLOR orange]TMDB : [/COLOR]PŘIDAT DO WATCHLISTU', f"RunPlugin({get_url(action='tmdb_add_watchlist', tmdb_id=tmdb_id, media_type=media_type)})"),
                ('[COLOR orange]TMDB : [/COLOR]PŘIDAT DO OBLÍBENÝCH', f"RunPlugin({get_url(action='tmdb_add_favorite', tmdb_id=tmdb_id, media_type=media_type)})"),
                ('[COLOR orange]TMDB : [/COLOR]OHODNOTIT POLOŽKU', f"RunPlugin({get_url(action='tmdb_rate', tmdb_id=tmdb_id, media_type=media_type)})")
            ])

        return context_menu_items

        if self.enable_trakt_context:
            trakt_media_type = 'movie' if media_type == 'movie' else 'show'
            trakt_id = trakt.get_trakt_id(tmdb_id, trakt_media_type, self.session, self.addon)
            if trakt_id:

                context_menu_items.append((
                    '[COLOR orange]TRAKT : [/COLOR]PŘIDAT DO WATCHLISTU',
                    f'RunPlugin({get_url(action="trakt_add_to_watchlist", media_type=trakt_media_type, media_id=trakt_id)})'
                ))



    def search(self, name=None, media_type=None):
        if not name:
            kb = xbmc.Keyboard('', '[COLOR orange]·   ZADEJTE NÁZEV  [ FUCKING ]  FILMU NEBO SERIÁLU   ·[/COLOR]')
            kb.doModal()
            # If user cancelled the keyboard and this was invoked as a router action,
            # ensure we close the directory to avoid Kodi showing a perpetual busy spinner.
            if not kb.isConfirmed() or not kb.getText().strip():
                try:
                    xbmcplugin.endOfDirectory(self._handle, succeeded=False)
                except Exception:
                    # best-effort: if not running inside Kodi or handle unavailable, ignore
                    pass
                return
            name = kb.getText().strip()

        # --- HISTORY : ULOŽENÍ VYHLEDÁVÁNÍ DO SOUBORU HISTORIE

        try:
            history_path = xbmcvfs.translatePath('special://userdata/PLAY-DATA/HISTORY/HISTORY.TXT')
            if xbmcvfs.exists(history_path):
                with xbmcvfs.File(history_path, 'r') as f:
                    lh = f.read().splitlines()
                if name not in lh:
                    if len(lh) >= 10: del lh[-1]
                    lh.insert(0, name)
                    with xbmcvfs.File(history_path, 'w') as f: f.write('\n'.join(lh))
            else:
                with xbmcvfs.File(history_path, 'w') as f: f.write(name)
        except Exception as e:
            log(f"TMDB - Chyba při ukládání do historie hledání : {e}", xbmc.LOGERROR)

        endpoint = "search/multi" if not media_type else f"search/{media_type}"
        params = {'query': name, 'page': 1}
        data = self._fetch(endpoint, params)
        if not data or not data.get('results'):
            xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', 'TMDB SEARCH : Žádné výsledky nenalezeny ...', xbmcgui.NOTIFICATION_INFO, 4000)
            xbmcplugin.endOfDirectory(self._handle, succeeded=False)
            return
        self.list_items(data, media_type or 'multi', 1, 'search_tmdb')



    def list_trending(self, page, media_type):
        endpoint = f"trending/{media_type}/week"
        params = {'page': page}
        cache_key = f"trending_{media_type}_page_{page}"
        data = self._fetch(endpoint, params, cache_key)
        if data:
            self.list_items(data, media_type, page, 'listing_trending')



    def list_discover(self, page, media_type):
        endpoint = f"discover/{media_type}"
        params = {'page': page, 'sort_by': 'popularity.desc'}
        cache_key = f"discover_{media_type}_page_{page}"
        data = self._fetch(endpoint, params, cache_key)
        if data:
            self.list_items(data, media_type, page, 'listing_discover')


    def list_top_rated(self, page, media_type):
        endpoint = f"{media_type}/top_rated"
        params = {'page': page}
        cache_key = f"top_rated_{media_type}_page_{page}"
        data = self._fetch(endpoint, params, cache_key)
        if data:
            self.list_items(data, media_type, page, 'listing_top_rated')



    def list_now_playing(self, page, media_type):
        if media_type != 'movie': return
        endpoint = f"{media_type}/now_playing"
        params = {'page': page}
        cache_key = f"now_playing_{media_type}_page_{page}"
        data = self._fetch(endpoint, params, cache_key)
        if data:
            self.list_items(data, media_type, page, 'listing_now_playing')



    def list_upcoming(self, page, media_type):
        if media_type != 'movie': return
        endpoint = f"{media_type}/upcoming"
        params = {'page': page}
        cache_key = f"upcoming_{media_type}_page_{page}"
        data = self._fetch(endpoint, params, cache_key)
        if data:
            self.list_items(data, media_type, page, 'listing_upcoming')



    def list_airing_today(self, page, media_type):
        if media_type != 'tv': return
        endpoint = f"{media_type}/airing_today"
        params = {'page': page}
        cache_key = f"airing_today_{media_type}_page_{page}"
        data = self._fetch(endpoint, params, cache_key)
        if data:
            self.list_items(data, media_type, page, 'listing_airing_today')



    def list_on_the_air(self, page, media_type):
        if media_type != 'tv': return
        endpoint = f"{media_type}/on_the_air"
        params = {'page': page}
        cache_key = f"on_the_air_{media_type}_page_{page}"
        data = self._fetch(endpoint, params, cache_key)
        if data:
            self.list_items(data, media_type, page, 'listing_on_the_air')



    def list_by_genre(self, page, media_type, genre_id):
        endpoint = f"discover/{media_type}"
        params = {'page': page, 'with_genres': genre_id}
        cache_key = f"genre_{media_type}_{genre_id}_page_{page}"
        data = self._fetch(endpoint, params, cache_key)
        if data:
            self.list_items(data, media_type, page, 'listing_genre')



    def list_by_year(self, page, media_type, year):
        endpoint = f"discover/{media_type}"
        year_param = 'primary_release_year' if media_type == 'movie' else 'first_air_date_year'
        params = {'page': page, year_param: year}
        cache_key = f"year_{media_type}_{year}_page_{page}"
        data = self._fetch(endpoint, params, cache_key)
        if data:
            self.list_items(data, media_type, page, 'listing_year')



    def list_genres_category(self, media_type):
        genres = self.get_genres(media_type)
        for genre_id, genre_name in genres.items():
            list_item = xbmcgui.ListItem(label=genre_name)
            list_item.setArt({'icon': 'special://home/addons/plugin.video.play_to/resources/icons/GENTRE.png'})
            url = get_url(action='listing_genre', type=media_type, id=str(genre_id), page='1')
            xbmcplugin.addDirectoryItem(self._handle, url, list_item, True)
        xbmcplugin.endOfDirectory(self._handle)



    def list_years_category(self, media_type):
        current_year = datetime.datetime.now().year
        years = list(range(current_year, current_year - 30, -1))
        for year in years:
            list_item = xbmcgui.ListItem(label=str(year))
            list_item.setArt({'icon': 'special://home/addons/plugin.video.play_to/resources/icons/YEAR.png'})
            url = get_url(action='listing_year', type=media_type, id=str(year), page='1')
            xbmcplugin.addDirectoryItem(self._handle, url, list_item, True)
        xbmcplugin.endOfDirectory(self._handle)



    def show_tv_detail(self, tmdb_id, meta_json):
        parent_meta = json.loads(meta_json)
        endpoint = f"tv/{tmdb_id}"
        cache_key = f"tv_detail_{tmdb_id}"
        data = self._fetch(endpoint, cache_key=cache_key)
        if not data: return

        for season in data.get('seasons', []):
            season_number = season['season_number']
            if season_number == 0: continue
            season_name = season.get('name', f'Sezóna {season_number}')
            poster_path = season.get('poster_path')
            poster = f"{self.image_base_url}w500{poster_path}" if poster_path else parent_meta.get('poster')
            list_item = xbmcgui.ListItem(label=season_name)
            info_tag = list_item.getVideoInfoTag()
            info_tag.setMediaType('season')
            info_tag.setTitle(season_name)
            info_tag.setTvShowTitle(parent_meta.get('title'))
            info_tag.setPlot(season.get('overview', ''))
            info_tag.setPremiered(season.get('air_date', ''))
            info_tag.setSeason(season_number)
            list_item.setArt({'poster': poster, 'thumb': poster, 'fanart': parent_meta.get('fanart')})
            url = get_url(action='tmdb_tv_season', tmdb_id=tmdb_id, season=season_number, meta=json.dumps(parent_meta))
            xbmcplugin.addDirectoryItem(self._handle, url, list_item, True)

        xbmcplugin.setContent(self._handle, 'seasons')
        xbmcplugin.endOfDirectory(self._handle)



    def show_tv_season(self, tmdb_id, season_number, meta_json):

        # --- FUTURE FIX : Potenciální oprava pro zamezení zbytečného znovunačítání po návratu z přehrávání.
        #
        # current_list_item_path = xbmc.getInfoLabel('ListItem.Path')
        # if f"action=tmdb_tv_season&tmdb_id={tmdb_id}&season={season_number}" in current_list_item_path:
        #     log("TMDB - Návrat do již existujícího seznamu sezóny. Přeskakuji nové načítání.", xbmc.LOGINFO)
        #     xbmcplugin.endOfDirectory(self._handle, succeeded=True)
        #     return

        parent_meta = json.loads(meta_json)
        endpoint = f"tv/{tmdb_id}/season/{season_number}"
        cache_key = f"tv_season_{tmdb_id}_{season_number}"
        data = self._fetch(endpoint, cache_key=cache_key)
        if not data: return

        for episode in data.get('episodes', []):
            episode_number = episode['episode_number']
            ep_title = episode.get('name', f'Epizoda {episode_number}')
            still_path = episode.get('still_path')
            thumb = f"{self.image_base_url}w500{still_path}" if still_path else parent_meta.get('fanart')
            list_item = xbmcgui.ListItem(label=f"{episode_number}. {ep_title}")
            info_tag = list_item.getVideoInfoTag()
            info_tag.setMediaType('episode')
            info_tag.setTitle(ep_title)
            info_tag.setPlot(episode.get('overview', ''))
            info_tag.setPremiered(episode.get('air_date', ''))
            info_tag.setTvShowTitle(parent_meta.get('title'))
            info_tag.setSeason(int(season_number))
            info_tag.setEpisode(episode_number)
            if self.show_tmdb_rating:
                info_tag.setRating(float(episode.get('vote_average', 0.0)))
            list_item.setArt({'thumb': thumb, 'icon': thumb, 'fanart': parent_meta.get('fanart')})

            episode_meta = parent_meta.copy()
            episode_meta.update({
                'media_type': 'episode', 'title': ep_title, 'plot': episode.get('overview', ''),
                'thumb': thumb, 'season': season_number, 'episode': episode_number,
                'tv_show_title': parent_meta.get('title'), 'rating': episode.get('vote_average', 0.0)
            })

            context_menu_items = [
                ('[COLOR orange]AUTOPLAY : [/COLOR]VYTVOŘIT PLAYLIST',
                 f"RunPlugin({get_url(action='create_series_playlist_action', meta=json.dumps(episode_meta))})")
            ]

            list_item.addContextMenuItems(context_menu_items, replaceItems=False)

            url = get_url(action='find_sources', meta=json.dumps(episode_meta))
            xbmcplugin.addDirectoryItem(self._handle, url, list_item, True)

        xbmcplugin.setContent(self._handle, 'episodes')
        xbmcplugin.endOfDirectory(self._handle)



    def list_account_items(self, list_type, media_type, page=1):
        if list_type == 'watchlist':
            data = tmdb_account.tmdb_get_watchlist(media_type, page)
        elif list_type == 'rated':
            data = tmdb_account.tmdb_get_rated(media_type, page)
        elif list_type == 'favorites':
            data = tmdb_account.tmdb_get_favorites(media_type, page)
        else:
            return

        if data:
            action_name = f'tmdb_{list_type}_{media_type}'
            self.list_items(data, media_type, page, action_name, context_type=list_type)
