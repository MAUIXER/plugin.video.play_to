# -*- coding: utf-8 -*-


# =========================================================================
#
#  Module: trakt
#  Author: MauiX ER
#  Created on: 13.10.2025
#  License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
# =========================================================================



import xbmc
import xbmcgui
import xbmcvfs
import xbmcaddon
import xbmcplugin

import os
import time
import json
import requests
import traceback

from datetime import datetime, date
from urllib.parse import parse_qsl, urlencode, urlparse


from resources.lib.utils import get_url, log, popinfo, safe_get, safe_post



TRAKT_OAUTH_URL = 'https://api.trakt.tv/oauth/'
TRAKT_AUTHORIZE_URL = TRAKT_OAUTH_URL + 'authorize'
TRAKT_TOKEN_URL = TRAKT_OAUTH_URL + 'token'
TRAKT_DEVICE_CODE_URL = TRAKT_OAUTH_URL + 'device/code'
TRAKT_DEVICE_TOKEN_URL = TRAKT_OAUTH_URL + 'device/token'



_CACHE_ROOT = None
_addon = xbmcaddon.Addon()
_session = requests.Session()
_handle = None
_trakt_cache = {}



CACHE_TTL_HOURS = int(_addon.getSetting('trakt_cache_ttl') or '24')
SHARED_CACHE_PATH = _addon.getSetting('shared_cache_path').strip()






# =======================     CONFIGURE CACHE     ======================================================================= #
# ======================================================================================================================= #


def _get_cache_dir():
    global _CACHE_ROOT
    if _CACHE_ROOT is None:
        if SHARED_CACHE_PATH:
            _CACHE_ROOT = xbmcvfs.translatePath(SHARED_CACHE_PATH)
        else:
            _CACHE_ROOT = xbmcvfs.translatePath(_addon.getAddonInfo('profile'))
        
        if not xbmcvfs.exists(_CACHE_ROOT):
            xbmcvfs.mkdirs(_CACHE_ROOT)
    return _CACHE_ROOT


def save_trakt_cache(cache_name, data):
    cache_path = os.path.join(_get_cache_dir(), f"{cache_name}.json")
    try:
        data_to_save = {'timestamp': time.time(), 'data': data}
        with xbmcvfs.File(cache_path, 'w') as f:
            content_to_write = json.dumps(data_to_save, ensure_ascii=False, indent=2)
            bytes_written = f.write(content_to_write)
            if bytes_written == 0 and content_to_write:
                raise IOError(f"Nepodařilo se zapsat data do cache souboru '{cache_name}' (0 bytes zapsáno)")
        log(f"TRAKT - Cache '{cache_name}' úspěšně uložena ...", xbmc.LOGINFO)
    except Exception as e:
        log(f"TRAKT - Chyba při ukládání cache '{cache_name}': {e}\n{traceback.format_exc()}", xbmc.LOGERROR)


def load_trakt_cache(cache_name):
    cache_path = os.path.join(_get_cache_dir(), f"{cache_name}.json")
    if xbmcvfs.exists(cache_path):
        try:
            f = None
            try:
                f = xbmcvfs.File(cache_path, 'r')
                content = f.read()
                if not content:
                    return None
                data = json.loads(content)
            finally:
                if f:
                    f.close()
            
            cache_age_seconds = time.time() - data.get('timestamp', 0)
            if cache_age_seconds < CACHE_TTL_HOURS * 3600:
                log(f"TRAKT - Používám cachovaná data pro '{cache_name}'.", xbmc.LOGINFO)
                return data.get('data')
            else:
                log(f"TRAKT - Cache pro '{cache_name}' vypršela. Stahuji nová data ...", xbmc.LOGINFO)
        except Exception as e:
            log(f"TRAKT - Chyba při načítání cache '{cache_name}': {str(e)}", xbmc.LOGERROR)
            traceback.print_exc()
            
    return None


# =======================     CONFIGURE ID     ========================================================================== #


def get_tmdb_id(trakt_id, media_type):

    key = f"{media_type}_{trakt_id}_tmdb"

    if key in _trakt_cache:
        return _trakt_cache[key]
    
    url = f"https://api.trakt.tv/{media_type}s/{trakt_id}"

    try:
        response = safe_get(_session, url, headers=trakt_get_headers(addon=_addon), timeout=5)
        if response is not None and response.status_code == 200:
            data = response.json()
            tmdb_id = data['ids']['tmdb']
            _trakt_cache[key] = tmdb_id
            return tmdb_id
        else:
            log(f"TRAKT - Chyba API pro Trakt ID {trakt_id} ({media_type}): {response.status_code if response is not None else 'no response'}", xbmc.LOGERROR)
    except Exception as e:
        log(f"TRAKT - Chyba při hledání TMDB ID pro {trakt_id} ({media_type}): {str(e)}", xbmc.LOGERROR)
    
    _trakt_cache[key] = None

    return None


def get_trakt_id(tmdb_id, media_type, session, addon):

    cache_key = f"tmdb_to_trakt_id_{media_type}_{tmdb_id}"
    cached_id = load_trakt_cache(cache_key)

    if cached_id is not None:
        return cached_id
    
    url = f"https://api.trakt.tv/search/tmdb/{tmdb_id}?type={media_type}"

    try:
        response = safe_get(session, url, headers=trakt_get_headers(addon=addon), timeout=5)
        if response is not None and response.status_code == 200:
            data = response.json()
            if data and len(data) > 0:
                trakt_id = data[0][media_type]['ids']['trakt']
                save_trakt_cache(cache_key, trakt_id)
                return trakt_id
            else:
                log(f"TRAKT - Žádná data pro TMDB ID {tmdb_id} ({media_type})", xbmc.LOGWARNING)
        else:
            log(f"TRAKT - Chyba API pro TMDB ID {tmdb_id} ({media_type}): {response.status_code if response is not None else 'no response'}", xbmc.LOGERROR)
    except Exception as e:
        log(f"TRAKT - Chyba při hledání Trakt ID pro {tmdb_id} ({media_type}): {str(e)}", xbmc.LOGERROR)
        
    return None


# =======================     LISTS  :  WATCHLISTS     ================================================================== #


def trakt_add_to_watchlist(params, addon, handle, session=None):

    global _session, _addon, _handle
    _addon = addon
    _handle = handle
    _session = session or _session

    trakt_client_id = _addon.getSetting('trakt_client_id').strip()
    access_token = _addon.getSetting('trakt_access_token').strip()

    if not trakt_client_id:
        popinfo("[COLOR orange]TRAKT.TV : [/COLOR]Pro přidání do watchlistu je třeba vyplnit CLIENT ID v nastavení", sound=True)
        _addon.openSettings()
        return

    if not access_token:
        popinfo("[COLOR orange]TRAKT.TV : [/COLOR]Pro tuto akci je třeba se připojit k TRAKT.TV", icon=xbmcgui.NOTIFICATION_ERROR)
        trakt_authenticate(addon=_addon, session=_session)
        return

    media_type = params.get('media_type', 'movie')
    media_id = params.get('media_id')

    if not media_id:
        popinfo("[COLOR orange]TRAKT.TV : [/COLOR]Chybí ID položky", icon=xbmcgui.NOTIFICATION_ERROR)
        return

    add_url = 'https://api.trakt.tv/sync/watchlist'
    add_data = {
        f"{media_type}s": [{'ids': {'trakt': int(media_id)}}]
    }

    try:
        response = safe_post(_session, add_url, headers=trakt_get_headers(addon=_addon, write=True), json=add_data, timeout=10)
        if response is not None and response.status_code == 401:
            if trakt_refresh_token(addon=_addon, session=_session):
                response = safe_post(_session, add_url, headers=trakt_get_headers(addon=_addon, write=True), json=add_data, timeout=10)

        if response is not None and response.status_code == 201:
            popinfo("[COLOR orange]TRAKT.TV : [/COLOR]Položka přidána do watchlistu", icon=xbmcgui.NOTIFICATION_INFO)
        else:
            popinfo("[COLOR orange]TRAKT.TV : [/COLOR]Chyba při přidávání : {response.status_code}", icon=xbmcgui.NOTIFICATION_ERROR)

    except Exception as e:
        log(f"TRAKT - Chyba při přidávání do watchlistu : {str(e)}", xbmc.LOGERROR)
        popinfo("[COLOR orange]TRAKT.TV : [/COLOR]Chyba při přidávání do watchlistu", icon=xbmcgui.NOTIFICATION_ERROR)

    xbmc.executebuiltin('Container.Refresh()')


# =======================     LISTS  :  POPULAR     ===================================================================== #


def trakt_popular_lists(params, addon, handle, session=None):

    global _session, _addon, _handle
    _addon = addon
    _handle = handle
    _session = session or _session

    xbmcplugin.setPluginCategory(_handle, "Trakt Popular Lists")
    trakt_client_id = _addon.getSetting('trakt_client_id').strip()

    if not trakt_client_id:
        popinfo("[COLOR red]TRAKT.TV : [/COLOR]Pro připojení je třeba vyplnit CLIENT ID v nastavení", sound=True)
        _addon.openSettings()
        xbmcplugin.endOfDirectory(_handle)
        return

    try:
        if 'list_id' not in params:
            cache_key = "trakt_popular_lists"
            lists = load_trakt_cache(cache_key)
            if not lists:
                url = 'https://api.trakt.tv/lists/popular?extended=full'
                response = _session.get(url, headers=trakt_get_headers(addon=_addon), timeout=10)
                
                if response.status_code != 200:
                    popinfo("[COLOR red]TRAKT.TV : [/COLOR]Chyba při načítání populárních seznamů", icon=xbmcgui.NOTIFICATION_ERROR)
                    return

                lists = response.json()
                save_trakt_cache(cache_key, lists)
            
            for item in lists:
                list_data = item['list']
                title = list_data.get('name', 'Neznámý seznam')
                list_id = list_data['ids']['trakt']
                
                listitem = xbmcgui.ListItem(label=title)
                listitem.setArt({'icon': 'DefaultFolder.png'})
                listitem.setInfo('video', {'plot': list_data.get('description', '')})
                
                xbmcplugin.addDirectoryItem(
                    _handle,
                    get_url(action='trakt_popular_lists', list_id=list_id),
                    listitem,
                    True
                )

            xbmcplugin.endOfDirectory(_handle)
            return

        list_id = params['list_id']
        cache_key = f"trakt_list_items_{list_id}"
        items = load_trakt_cache(cache_key)

        if not items:
            url = f'https://api.trakt.tv/lists/{list_id}/items?extended=full,images'
            response = safe_get(_session, url, headers=trakt_get_headers(addon=_addon), timeout=10)
            
            if response is None or response.status_code != 200:
                popinfo("[COLOR red]TRAKT.TV : [/COLOR]Chyba při načítání položek seznamu", icon=xbmcgui.NOTIFICATION_ERROR)
                return

            items = response.json()
            save_trakt_cache(cache_key, items)
            
        for item in items:
            media_type = item.get('type')
            if media_type not in ['movie', 'show']:
                continue
            
            media = item[media_type]
            media_id = media['ids']['trakt']
            tmdb_id = media['ids'].get('tmdb')
            title = media.get('title', 'Neznámý název')
            year = media.get('year', '')

            if year:
                title = f"{title} ({year})"
                
            artwork = {}
            if isinstance(media.get('images'), dict):
                images = media['images']

                if 'poster' in images and isinstance(images['poster'], list) and len(images['poster']) > 0:
                    poster_url = images['poster'][0]
                    artwork['poster'] = f"https://{poster_url}" if not poster_url.startswith('http') else poster_url
                if 'fanart' in images and isinstance(images['fanart'], list) and len(images['fanart']) > 0:
                    fanart_url = images['fanart'][0]
                    artwork['fanart'] = f"https://{fanart_url}" if not fanart_url.startswith('http') else fanart_url
                artwork['thumb'] = artwork.get('poster', '')
            
            listitem = xbmcgui.ListItem(label=title)
            if artwork:
                listitem.setArt(artwork)

            # context_menu_items = []
            # if media.get('trailer'):
            #    trailer_url = media['trailer']
            #    if 'youtube.com' in trailer_url or 'youtu.be' in trailer_url:
            #        video_id = trailer_url.split('v=')[-1].split('&')[0]
            #        youtube_plugin_url = f'plugin://plugin.video.youtube/play/?video_id={video_id}'
            #        context_menu_items.append(("[COLOR orange]TRAKT : [/COLOR]Přehrát trailer", f'PlayMedia({youtube_plugin_url})'))

            context_menu_items = []

            if media.get('trailer'):
                trailer_url = media['trailer']
                if 'youtube.com' in trailer_url or 'youtu.be' in trailer_url:
                    video_id = trailer_url.split('v=')[-1].split('&')[0]
                    invidious_plugin_url = f'plugin://plugin.video.mau_vidious/?action=play&videoId={video_id}'

                    context_menu_items.append((
                        "[COLOR orange]TRAKT : [/COLOR]PŘEHRÁT TRAILER",
                        f'PlayMedia({invidious_plugin_url})'
                    ))
        
            # context_menu_items.append(('[COLOR orange]TRAKT : [/COLOR]VYHLEDAT TITUL', f'Container.Update({get_url(action="search", what=media.get("title", ""))})'))
            context_menu_items.append(('[COLOR orange]TRAKT : [/COLOR]PŘIDAT DO WATCHLISTU', f'RunPlugin({get_url(action="trakt_add_to_watchlist", media_type=media_type, media_id=media_id)})'))
            
            listitem.addContextMenuItems(context_menu_items)

            info_tag = listitem.getVideoInfoTag()
            info_tag.setMediaType(media_type)
            info_tag.setTitle(title)
            info_tag.setPlot(media.get('overview', ''))

            if year:
                try:
                    info_tag.setYear(int(year))
                except (ValueError, TypeError):
                    log(f"TRAKT - Chyba při nastavení roku pro '{title}': Neplatná hodnota '{year}'", xbmc.LOGWARNING)

            info_tag.setGenres(media.get('genres', []))

            if media.get('runtime'):
                try:
                    info_tag.setDuration(media.get('runtime', 0) * 60)
                except (ValueError, TypeError):
                    log(f"TRAKT - Chyba při nastavení délky pro '{title}': Neplatná hodnota '{media.get('runtime')}'", xbmc.LOGWARNING)

            if media.get('rating'):
                try:
                    info_tag.setRating(float(media.get('rating', 0)))
                except (ValueError, TypeError):
                    log(f"TRAKT - Chyba při hodnocení pro '{title}': Neplatná hodnota '{media.get('rating')}'", xbmc.LOGWARNING)

            meta = {
                'tmdb_id': tmdb_id,
                'title': media.get('title') or title,
                'year': year,
                'plot': media.get('overview', ''),
                'poster': artwork.get('poster', ''),
                'fanart': artwork.get('fanart', ''),
                'rating': media.get('rating', 0.0),
                'genres': media.get('genres', []),
                'media_type': media_type
            }

            item_url = get_url(action='find_sources', meta=json.dumps(meta)) if media_type == 'movie' else get_url(action='trakt_watchlist', show_id=media_id, category='shows')

            xbmcplugin.addDirectoryItem(
                _handle,
                item_url,
                listitem,
                True
            )

        xbmcplugin.setContent(_handle, 'movies' if media_type == 'movie' else 'tvshows')
        xbmcplugin.endOfDirectory(_handle)

    except Exception as e:
        log(f"TRAKT - Chyba při načítání populárních seznamů : {str(e)}", xbmc.LOGERROR)
        popinfo("[COLOR red]TRAKT.TV : [/COLOR]Chyba při načítání", icon=xbmcgui.NOTIFICATION_ERROR)

        traceback.print_exc()


# =======================     LISTS  :  RECOMMENDED     ================================================================= #


def trakt_recommended(params, addon, handle, session=None):

    global _session, _addon, _handle
    _addon = addon
    _handle = handle
    _session = session or _session

    xbmcplugin.setPluginCategory(_handle, "Trakt Recommended")
    trakt_client_id = _addon.getSetting('trakt_client_id').strip()
    access_token = _addon.getSetting('trakt_access_token').strip()

    if not trakt_client_id:
        popinfo("[COLOR red]TRAKT.TV : [/COLOR]Pro připojení je třeba vyplnit CLIENT ID a CLIENT SECRET v nastavení", sound=True)
        _addon.openSettings()
        xbmcplugin.endOfDirectory(_handle)
        return

    if not access_token:
        popinfo("[COLOR red]TRAKT.TV : [/COLOR]Pro doporučené je třeba se připojit", icon=xbmcgui.NOTIFICATION_ERROR)
        trakt_authenticate(addon=_addon, session=_session)
        return

    category = params.get('category', 'movies')
    media_type = 'movie' if category == 'movies' else 'show'
    cache_key = f"trakt_recommended_{category}"
    items = load_trakt_cache(cache_key)

    if not items:
        url = f'https://api.trakt.tv/recommendations/{category}?extended=full,images'
        response = _session.get(url, headers=trakt_get_headers(addon=_addon, write=True), timeout=10)
        response = handle_trakt_401(url, addon=_addon, session=_session)

        if not response or response.status_code != 200:
            popinfo("[COLOR red]TRAKT.TV : [/COLOR]Chyba při načítání doporučených", icon=xbmcgui.NOTIFICATION_ERROR)
            return

        items = response.json()
        save_trakt_cache(cache_key, items)

    for media in items:
        media_id = media['ids']['trakt']
        tmdb_id = media['ids'].get('tmdb')
        title = media.get('title', 'Neznámý název')
        year = media.get('year', '')
        if year:
            title = f"{title} ({year})"

        try:
            translation_url = f'https://api.trakt.tv/{media_type}s/{media_id}/translations/{_addon.getSetting("trakt_language").strip()}'
            translation_response = _session.get(translation_url, headers=trakt_get_headers(addon=_addon), timeout=10)
            if translation_response.status_code == 200:
                translation = translation_response.json()
                if translation and isinstance(translation, list):
                    title = translation[0].get('title', title)
                    plot = translation[0].get('overview', media.get('overview', ''))
                else:
                    plot = media.get('overview', '')
            else:
                plot = media.get('overview', '')
        except Exception:
            plot = media.get('overview', '')

        artwork = {}

        if isinstance(media.get('images'), dict):
            images = media['images']
            if 'poster' in images and isinstance(images['poster'], list) and len(images['poster']) > 0:
                poster_url = images['poster'][0]
                artwork['poster'] = f"https://{poster_url}" if not poster_url.startswith('http') else poster_url
            if 'fanart' in images and isinstance(images['fanart'], list) and len(images['fanart']) > 0:
                fanart_url = images['fanart'][0]
                artwork['fanart'] = f"https://{fanart_url}" if not fanart_url.startswith('http') else fanart_url
            artwork['thumb'] = artwork.get('poster', '')

        listitem = xbmcgui.ListItem(label=title)
        if artwork:
            listitem.setArt(artwork)

        context_menu_items = []
        if media.get('trailer'):
            trailer_url = media['trailer']
            if 'youtube.com' in trailer_url or 'youtu.be' in trailer_url:
                video_id = trailer_url.split('v=')[-1].split('&')[0]
                invidious_plugin_url = f'plugin://plugin.video.mau_vidious/?action=play&videoId={video_id}'
                context_menu_items.append((
                    "[COLOR orange]TRAKT : [/COLOR]PŘEHRÁT TRAILER",
                    f'PlayMedia({invidious_plugin_url})'
                ))

        # context_menu_items.append(('[COLOR orange]TRAKT : [/COLOR]VYHLEDAT TITUL', f'Container.Update({get_url(action="search", what=media.get("title", ""))})'))
        context_menu_items.append(('[COLOR orange]TRAKT : [/COLOR]PŘIDAT DO WATCHLISTU', f'RunPlugin({get_url(action="trakt_add_to_watchlist", media_type=media_type, media_id=media_id)})'))
            
        listitem.addContextMenuItems(context_menu_items)

        info_tag = listitem.getVideoInfoTag()
        info_tag.setMediaType(media_type)
        info_tag.setTitle(title)
        info_tag.setPlot(plot)

        if year:
            try:
                info_tag.setYear(int(year))
            except (ValueError, TypeError):
                log(f"TRAKT - Chyba při nastavení roku pro '{title}': Neplatná hodnota '{year}'", xbmc.LOGWARNING)

        info_tag.setGenres(media.get('genres', []))

        if media.get('runtime'):
            try:
                info_tag.setDuration(media.get('runtime', 0) * 60)
            except (ValueError, TypeError):
                log(f"TRAKT - Chyba při nastavení délky pro '{title}': Neplatná hodnota '{media.get('runtime')}'", xbmc.LOGWARNING)

        if media.get('rating'):
            try:
                info_tag.setRating(float(media.get('rating', 0)))
            except (ValueError, TypeError):
                log(f"TRAKT - Chyba při hodnocení pro '{title}': Neplatná hodnota '{media.get('rating')}'", xbmc.LOGWARNING)

        meta = {
            'tmdb_id': tmdb_id,
            'title': media.get('title') or title,
            'year': year,
            'plot': plot,
            'poster': artwork.get('poster', ''),
            'fanart': artwork.get('fanart', ''),
            'rating': media.get('rating', 0.0),
            'genres': media.get('genres', []),
            'media_type': media_type
        }

        item_url = get_url(action='find_sources', meta=json.dumps(meta)) if media_type == 'movie' else get_url(action='trakt_watchlist', show_id=media_id, category='shows')

        xbmcplugin.addDirectoryItem(
            _handle,
            item_url,
            listitem,
            True
        )

    xbmcplugin.setContent(_handle, 'movies' if category == 'movies' else 'tvshows')
    xbmcplugin.endOfDirectory(_handle)


# =======================     LISTS  :  TRENDING     ==================================================================== #


def trakt_trending(params, addon, handle, session=None):

    global _session, _addon, _handle
    _addon = addon
    _handle = handle
    _session = session or _session

    xbmcplugin.setPluginCategory(_handle, "Trakt Trending")
    trakt_client_id = _addon.getSetting('trakt_client_id').strip()

    if not trakt_client_id:
        popinfo("[COLOR red]TRAKT.TV : [/COLOR]Pro připojení je třeba vyplnit CLIENT ID a CLIENT SECRET v nastavení", sound=True)
        _addon.openSettings()
        xbmcplugin.endOfDirectory(_handle)
        return

    category = params.get('category', 'movies')
    cache_key = f"trakt_trending_{category}"
    items = load_trakt_cache(cache_key)

    if not items:
        url = f'https://api.trakt.tv/{category}/trending?extended=full,images'
        response = _session.get(url, headers=trakt_get_headers(addon=_addon), timeout=10)

        if response.status_code != 200:
            popinfo("[COLOR red]TRAKT.TV : [/COLOR]Chyba při načítání trendů", icon=xbmcgui.NOTIFICATION_ERROR)
            return

        items = response.json()
        save_trakt_cache(cache_key, items)

    media_type = 'movie' if category == 'movies' else 'show'

    for item in items:
        media = item[media_type]
        media_id = media['ids']['trakt']
        tmdb_id = media['ids'].get('tmdb')
        title = media.get('title', 'Neznámý název')
        year = media.get('year', '')

        if year:
            title = f"{title} ({year})"

        try:
            translation_url = f'https://api.trakt.tv/{media_type}s/{media_id}/translations/{_addon.getSetting("trakt_language").strip()}'
            translation_response = _session.get(translation_url, headers=trakt_get_headers(addon=_addon), timeout=10)
            if translation_response.status_code == 200:
                translation = translation_response.json()
                if translation and isinstance(translation, list):
                    title = translation[0].get('title', title)
                    plot = translation[0].get('overview', media.get('overview', ''))
                else:
                    plot = media.get('overview', '')
            else:
                plot = media.get('overview', '')
        except Exception:
            plot = media.get('overview', '')

        artwork = {}

        if isinstance(media.get('images'), dict):
            images = media['images']
            if 'poster' in images and isinstance(images['poster'], list) and len(images['poster']) > 0:
                poster_url = images['poster'][0]
                artwork['poster'] = f"https://{poster_url}" if not poster_url.startswith('http') else poster_url
            if 'fanart' in images and isinstance(images['fanart'], list) and len(images['fanart']) > 0:
                fanart_url = images['fanart'][0]
                artwork['fanart'] = f"https://{fanart_url}" if not fanart_url.startswith('http') else fanart_url
            artwork['thumb'] = artwork.get('poster', '')

        listitem = xbmcgui.ListItem(label=title)

        if artwork:
            listitem.setArt(artwork)

        context_menu_items = []

        if media.get('trailer'):
            trailer_url = media['trailer']
            if 'youtube.com' in trailer_url or 'youtu.be' in trailer_url:
                video_id = trailer_url.split('v=')[-1].split('&')[0]
                invidious_plugin_url = f'plugin://plugin.video.mau_vidious/?action=play&videoId={video_id}'
                context_menu_items.append((
                    "[COLOR orange]TRAKT : [/COLOR]PŘEHRÁT TRAILER",
                    f'PlayMedia({invidious_plugin_url})'
                ))

        # context_menu_items.append(('[COLOR orange]TRAKT : [/COLOR]VYHLEDAT TITUL', f'Container.Update({get_url(action="search", what=media.get("title", ""))})'))
        context_menu_items.append(('[COLOR orange]TRAKT : [/COLOR]PŘIDAT DO WATCHLISTU', f'RunPlugin({get_url(action="trakt_add_to_watchlist", media_type=media_type, media_id=media_id)})'))
            
        listitem.addContextMenuItems(context_menu_items)

        info_tag = listitem.getVideoInfoTag()
        info_tag.setMediaType(media_type)
        info_tag.setTitle(title)
        info_tag.setPlot(plot)

        if year:
            try:
                info_tag.setYear(int(year))
            except (ValueError, TypeError):
                log(f"TRAKT - Chyba při nastavení roku pro '{title}': Neplatná hodnota '{year}'", xbmc.LOGWARNING)

        info_tag.setGenres(media.get('genres', []))

        if media.get('runtime'):
            try:
                info_tag.setDuration(media.get('runtime', 0) * 60)
            except (ValueError, TypeError):
                log(f"TRAKT - Chyba při nastavení délky pro '{title}': Neplatná hodnota '{media.get('runtime')}'", xbmc.LOGWARNING)

        if media.get('rating'):
            try:
                info_tag.setRating(float(media.get('rating', 0)))
            except (ValueError, TypeError):
                log(f"TRAKT - Chyba při hodnocení pro '{title}': Neplatná hodnota '{media.get('rating')}'", xbmc.LOGWARNING)

        meta = {
            'tmdb_id': tmdb_id,
            'title': media.get('title') or title,
            'year': year,
            'plot': plot,
            'poster': artwork.get('poster', ''),
            'fanart': artwork.get('fanart', ''),
            'rating': media.get('rating', 0.0),
            'genres': media.get('genres', []),
            'media_type': media_type
        }

        item_url = get_url(action='find_sources', meta=json.dumps(meta)) if media_type == 'movie' else get_url(action='trakt_watchlist', show_id=media_id, category='shows')

        xbmcplugin.addDirectoryItem(
            _handle,
            item_url,
            listitem,
            True
        )

    xbmcplugin.setContent(_handle, 'movies' if category == 'movies' else 'tvshows')
    xbmcplugin.endOfDirectory(_handle)


# =======================     LISTS  :  GENTRE  |  YEAR     ============================================================= #


def trakt_genres(params, addon, handle, session=None):

    global _session, _addon, _handle
    _addon = addon
    _handle = handle
    _session = session or _session

    xbmcplugin.setPluginCategory(_handle, "Trakt Genres")
    trakt_client_id = _addon.getSetting('trakt_client_id').strip()

    if not trakt_client_id:
        popinfo("[COLOR red]TRAKT.TV : [/COLOR]Pro připojení je třeba vyplnit CLIENT ID a CLIENT SECRET v nastavení", sound=True)
        _addon.openSettings()
        xbmcplugin.endOfDirectory(_handle)
        return

    category = params.get('category', 'movies')
    media_type = 'movie' if category == 'movies' else 'show'

    if 'genre' not in params:
        cache_key = f"trakt_genres_{category}"
        genres = load_trakt_cache(cache_key)

        if not genres:
            url = f'https://api.trakt.tv/genres/{category}'
            response = _session.get(url, headers=trakt_get_headers(addon=_addon), timeout=10)

            if response.status_code != 200:
                popinfo("[COLOR red]TRAKT.TV : [/COLOR]Chyba při načítání žánrů", icon=xbmcgui.NOTIFICATION_ERROR)
                return

            genres = response.json()
            save_trakt_cache(cache_key, genres)

        for genre in genres:
            title = genre['name']
            slug = genre['slug']

            listitem = xbmcgui.ListItem(label=title)
            listitem.setArt({'icon': 'DefaultFolder.png'})

            url = get_url(action='trakt_genres', category=category, genre=slug)
            xbmcplugin.addDirectoryItem(
                _handle,
                url,
                listitem,
                True
            )

        xbmcplugin.endOfDirectory(_handle)
        return

    genre = params['genre']
    year = params.get('year', '')

    if not year:
        kb = xbmc.Keyboard('', '[COLOR orange]·   ZADEJTE  [ FUCKING ]  ROK NEBO ROZSAH  ( 2020-2025 )   ·[/COLOR]')
        kb.doModal()
        # ensure directory is closed if user cancels while invoked via router
        if not kb.isConfirmed():
            try:
                xbmcplugin.endOfDirectory(_handle, succeeded=False)
            except Exception:
                pass
        else:
            year = kb.getText().strip()

    cache_key = f"trakt_genre_items_{category}_{genre}_{year}"
    items = load_trakt_cache(cache_key)

    if not items:
        query = f'genres={genre}'
        if year:
            query += f'&years={year}'
        url = f'https://api.trakt.tv/{category}/popular?extended=full,images&{query}'
        response = _session.get(url, headers=trakt_get_headers(addon=_addon), timeout=10)

        if response.status_code != 200:
            popinfo("[COLOR red]TRAKT.TV : [/COLOR]Chyba při načítání položek žánru", icon=xbmcgui.NOTIFICATION_ERROR)
            return

        items = response.json()
        save_trakt_cache(cache_key, items)

    for media in items:
        media_id = media['ids']['trakt']
        tmdb_id = media['ids'].get('tmdb')
        title = media.get('title', 'Neznámý název')
        year_val = media.get('year', '')

        if year_val:
            title = f"{title} ({year_val})"

        try:
            translation_url = f'https://api.trakt.tv/{media_type}s/{media_id}/translations/{_addon.getSetting("trakt_language").strip()}'
            translation_response = _session.get(translation_url, headers=trakt_get_headers(addon=_addon), timeout=10)
            if translation_response.status_code == 200:
                translation = translation_response.json()
                if translation and isinstance(translation, list):
                    title = translation[0].get('title', title)
                    plot = translation[0].get('overview', media.get('overview', ''))
                else:
                    plot = media.get('overview', '')
            else:
                plot = media.get('overview', '')
        except Exception:
            plot = media.get('overview', '')

        artwork = {}

        if isinstance(media.get('images'), dict):
            images = media['images']
            if 'poster' in images and isinstance(images['poster'], list) and len(images['poster']) > 0:
                poster_url = images['poster'][0]
                artwork['poster'] = f"https://{poster_url}" if not poster_url.startswith('http') else poster_url
            if 'fanart' in images and isinstance(images['fanart'], list) and len(images['fanart']) > 0:
                fanart_url = images['fanart'][0]
                artwork['fanart'] = f"https://{fanart_url}" if not fanart_url.startswith('http') else fanart_url
            artwork['thumb'] = artwork.get('poster', '')

        listitem = xbmcgui.ListItem(label=title)

        if artwork:
            listitem.setArt(artwork)

        context_menu_items = []

        if media.get('trailer'):
            trailer_url = media['trailer']
            if 'youtube.com' in trailer_url or 'youtu.be' in trailer_url:
                video_id = trailer_url.split('v=')[-1].split('&')[0]
                invidious_plugin_url = f'plugin://plugin.video.mau_vidious/?action=play&videoId={video_id}'
                context_menu_items.append((
                    "[COLOR orange]TRAKT : [/COLOR]PŘEHRÁT TRAILER",
                    f'PlayMedia({invidious_plugin_url})'
                ))

        # context_menu_items.append(('[COLOR orange]TRAKT : [/COLOR]VYHLEDAT TITUL', f'Container.Update({get_url(action="search", what=media.get("title", ""))})'))
        context_menu_items.append(('[COLOR orange]TRAKT : [/COLOR]PŘIDAT DO WATCHLISTU', f'RunPlugin({get_url(action="trakt_add_to_watchlist", media_type=media_type, media_id=media_id)})'))
         
        listitem.addContextMenuItems(context_menu_items)

        info_tag = listitem.getVideoInfoTag()
        info_tag.setMediaType(media_type)
        info_tag.setTitle(title)
        info_tag.setPlot(plot)

        if year_val:
            try:
                info_tag.setYear(int(year_val))
            except (ValueError, TypeError):
                log(f"TRAKT - Chyba při nastavení roku pro '{title}': Neplatná hodnota '{year_val}'", xbmc.LOGWARNING)

        info_tag.setGenres(media.get('genres', []))

        if media.get('runtime'):
            try:
                info_tag.setDuration(media.get('runtime', 0) * 60)
            except (ValueError, TypeError):
                log(f"TRAKT - Chyba při nastavení délky pro '{title}': Neplatná hodnota '{media.get('runtime')}'", xbmc.LOGWARNING)

        if media.get('rating'):
            try:
                info_tag.setRating(float(media.get('rating', 0)))
            except (ValueError, TypeError):
                log(f"TRAKT - Chyba při hodnocení pro '{title}': Neplatná hodnota '{media.get('rating')}'", xbmc.LOGWARNING)

        meta = {
            'tmdb_id': tmdb_id,
            'title': media.get('title') or title,
            'year': year_val,
            'plot': plot,
            'poster': artwork.get('poster', ''),
            'fanart': artwork.get('fanart', ''),
            'rating': media.get('rating', 0.0),
            'genres': media.get('genres', []),
            'media_type': media_type
        }

        item_url = get_url(action='find_sources', meta=json.dumps(meta)) if media_type == 'movie' else get_url(action='trakt_watchlist', show_id=media_id, category='shows')

        xbmcplugin.addDirectoryItem(
            _handle,
            item_url,
            listitem,
            True
        )

    xbmcplugin.setContent(_handle, 'movies' if category == 'movies' else 'tvshows')
    xbmcplugin.endOfDirectory(_handle)


# =======================     M A I N   M E N U   :   TRAKT.TV     ====================================================== #
# ======================================================================================================================= #


def trakt_menu(params, addon, handle, session=None):

    global _session, _addon, _handle
    _addon = addon
    _handle = handle
    _session = session or _session

    xbmcplugin.setPluginCategory(_handle, "Trakt Menu")



    # --- TRAKT.TV : Watchlist
    listitem = xbmcgui.ListItem(label="[B][COLOR orange]·  [/COLOR][/B]WATCHLISTY")
    listitem.setArt({'icon': 'DefaultVideoPlaylists.png'})
    xbmcplugin.addDirectoryItem(
        _handle,
        get_url(action='trakt_watchlist'),
        listitem,
        True
    )

    # --- TRAKT.TV : Popular Lists
    listitem = xbmcgui.ListItem(label="[B][COLOR orange]·  [/COLOR][/B]POPULÁRNÍ PLAYLISTY")
    listitem.setArt({'icon': 'DefaultVideoPlaylists.png'})
    xbmcplugin.addDirectoryItem(
        _handle,
        get_url(action='trakt_popular_lists'),
        listitem,
        True
    )

    # --- TRAKT.TV : Podle žánrů
    listitem = xbmcgui.ListItem(label="[B][COLOR orange]·  [/COLOR][/B]PODLE ŽÁNRU A ROKU")
    listitem.setArt({'icon': 'DefaultVideoPlaylists.png'})
    xbmcplugin.addDirectoryItem(
        _handle,
        get_url(action='trakt_genres'),
        listitem,
        True
    )

    # --- TRAKT.TV : Doporučené
    listitem = xbmcgui.ListItem(label="[B][COLOR orange]·  [/COLOR][/B]FILMY : DOPORUČENÉ")
    listitem.setArt({'icon': 'special://home/addons/plugin.video.play_to/resources/icons/TRAKT-RED.png'})
    xbmcplugin.addDirectoryItem(
        _handle,
        get_url(action='trakt_recommended'),
        listitem,
        True
    )

    # --- TRAKT.TV : Trendy
    listitem = xbmcgui.ListItem(label="[B][COLOR orange]·  [/COLOR][/B]FILMY : TRENDY")
    listitem.setArt({'icon': 'special://home/addons/plugin.video.play_to/resources/icons/TRAKT-RED.png'})
    xbmcplugin.addDirectoryItem(
        _handle,
        get_url(action='trakt_trending'),
        listitem,
        True
    )

    # --- TRAKT.TV : Authentication
    if not _addon.getSetting('trakt_access_token'):
        listitem = xbmcgui.ListItem(label="[B][COLOR orange]·  [ PŘIPOJIT KE TRAKT.TV ][/COLOR][/B]")
        listitem.setArt({'icon': 'special://home/addons/plugin.video.play_to/resources/icons/TRAKT-RED.png'})
        xbmcplugin.addDirectoryItem(
            _handle,
            get_url(action='trakt_watchlist', reauth=1),
            listitem,
            False
        )

    xbmcplugin.endOfDirectory(_handle)


# =======================     T R A K T . T V   :   WATCHLISTS     ====================================================== #
# ======================================================================================================================= #


def trakt_watchlist(params, addon, handle, session=None):

    global _session, _addon, _handle
    _addon = addon
    _handle = handle
    _session = session or _session

    xbmcplugin.setPluginCategory(_handle, "Trakt Watchlist")

    if 'reauth' in params:
        if trakt_authenticate(addon=_addon, session=_session):
            xbmc.executebuiltin('Container.Refresh()')
        return

    trakt_client_id = _addon.getSetting('trakt_client_id').strip()

    if not trakt_client_id:
        popinfo("[COLOR orange]TRAKT.TV : [/COLOR]Pro připojení je třeba vyplnit CLIENT ID a CLIENT SECRET v nastavení", sound=True)
        _addon.openSettings()
        xbmcplugin.endOfDirectory(_handle)
        return

    try:
        if 'category' not in params:
            listitem = xbmcgui.ListItem(label="[B][COLOR orange]·  [/COLOR][/B]WATCHLIST : FILMY")
            listitem.setArt({'icon': 'DefaultMovies.png'})
            xbmcplugin.addDirectoryItem(
                _handle,
                get_url(action='trakt_watchlist', category='movies'),
                listitem,
                True
            )

            listitem = xbmcgui.ListItem(label="[B][COLOR orange]·  [/COLOR][/B]WATCHLIST : SERIÁLY")
            listitem.setArt({'icon': 'DefaultTVShows.png'})
            xbmcplugin.addDirectoryItem(
                _handle,
                get_url(action='trakt_watchlist', category='shows'),
                listitem,
                True
            )

            xbmcplugin.endOfDirectory(_handle)
            return

        if 'remove' in params:
            access_token = _addon.getSetting('trakt_access_token').strip()

            if not access_token:
                popinfo("[COLOR orange]TRAKT.TV : [/COLOR]Pro tuto akci je potřeba připojit se ke TRAKT.TV", icon=xbmcgui.NOTIFICATION_ERROR)
                xbmcplugin.endOfDirectory(_handle)
                return

            media_type = 'movie' if params['category'] == 'movies' else 'show'
            remove_url = f'https://api.trakt.tv/sync/watchlist/remove'
            remove_data = {
                media_type + 's': [{'ids': {'trakt': int(params['remove'])}}]
            }
            
            response = _session.post(remove_url, headers=trakt_get_headers(addon=_addon, write=True), json=remove_data, timeout=10)
            
            if response.status_code == 401:
                if trakt_refresh_token(addon=_addon, session=_session):
                    response = _session.post(remove_url, headers=trakt_get_headers(addon=_addon, write=True), json=remove_data, timeout=10)
            
            if response.status_code == 200:
                popinfo("[COLOR orange]TRAKT.TV : [/COLOR]Položka odstraněna z WATCHLISTU", icon=xbmcgui.NOTIFICATION_INFO)
            elif response.status_code == 401:
                popinfo("[COLOR orange]TRAKT.TV : [/COLOR]Timeout pro připojení vypršel", icon=xbmcgui.NOTIFICATION_ERROR)
            else:
                popinfo("[COLOR orange]TRAKT.TV : [/COLOR]Chyba při odstraňování : {response.status_code}", icon=xbmcgui.NOTIFICATION_ERROR)
            
            xbmc.executebuiltin('Container.Refresh()')
            return
        
        if 'show_id' in params and 'season' not in params:
            return list_seasons(params, addon=_addon, handle=_handle, session=_session)
        
        if 'show_id' in params and 'season' in params:
            return list_episodes(params, addon=_addon, handle=_handle, session=_session)
        
        url = f'https://api.trakt.tv/users/me/watchlist/{params["category"]}?extended=full,images'
        response = _session.get(url, headers=trakt_get_headers(addon=_addon), timeout=10)
        response = handle_trakt_401(url, addon=_addon, session=_session)

        if not response or response.status_code != 200:
            return
        
        items = response.json()
        items = sorted(items, key=lambda x: x['movie']['title'] if 'movie' in x else x['show']['title'])
        
        for item in items:
            if params['category'] == 'movies' and 'movie' in item:
                media = item['movie']
                media_type = 'movie'
                media_id = media['ids']['trakt']
                tmdb_id = media['ids'].get('tmdb')
                
                try:
                    translation_url = f'https://api.trakt.tv/{media_type}s/{media_id}/translations/{_addon.getSetting("trakt_language").strip()}'
                    translation_response = _session.get(translation_url, headers=trakt_get_headers(addon=_addon), timeout=10)
                    if translation_response.status_code == 200:
                        translation = translation_response.json()
                        if translation and isinstance(translation, list):
                            title = translation[0].get('title', media.get('title', 'Neznámý název'))
                            plot = translation[0].get('overview', media.get('overview', ''))
                        else:
                            title = media.get('title', 'Neznámý název')
                            plot = media.get('overview', '')
                    else:
                        title = media.get('title', 'Neznámý název')
                        plot = media.get('overview', '')
                except Exception as e:
                    log(f"TRAKT - Chyba při načítání překladu : {str(e)}", xbmc.LOGERROR)
                    title = media.get('title', 'Neznámý název')
                    plot = media.get('overview', '')

                if not title:
                    title = media.get('title', 'Neznámý název')
                
                year = media.get('year', '')
                if year:
                    title = f"{title} ({year})"
                
                artwork = {}

                if isinstance(media.get('images'), dict):
                    images = media['images']
                    if isinstance(images.get('poster'), list) and len(images['poster']) > 0:
                        poster_url = images['poster'][0]
                        artwork['poster'] = f"https://{poster_url}" if not poster_url.startswith('http') else poster_url
                    if isinstance(images.get('fanart'), list) and len(images['fanart']) > 0:
                        fanart_url = images['fanart'][0]
                        artwork['fanart'] = f"https://{fanart_url}" if not fanart_url.startswith('http') else fanart_url
                    artwork['thumb'] = artwork.get('poster', '')
                
                listitem = xbmcgui.ListItem(label=title)

                if artwork:
                    listitem.setArt(artwork)
                
                context_menu_items = []
                
                # if media.get('trailer'):
                #     trailer_url = media['trailer']
                #     if 'youtube.com' in trailer_url or 'youtu.be' in trailer_url:
                #         video_id = trailer_url.split('v=')[-1].split('&')[0]
                #         youtube_plugin_url = f'plugin://plugin.video.mau_vidious/?action=play&videoId={video_id}'
                #         context_menu_items.append((
                #             "[COLOR orange]TRAKT.TV : [/COLOR] PŘEHRÁT TRAILER",
                #             f'PlayMedia({youtube_plugin_url})'
                #         ))    
                        
                if media.get('trailer'):
                    trailer_url = media['trailer']
                    if 'youtube.com' in trailer_url or 'youtu.be' in trailer_url:
                        video_id = trailer_url.split('v=')[-1].split('&')[0]
                        invidious_plugin_url = f'plugin://plugin.video.mau_vidious/?action=play&videoId={video_id}'

                        context_menu_items.append((
                            "[COLOR orange]TRAKT : [/COLOR]PŘEHRÁT TRAILER",
                            f'PlayMedia({invidious_plugin_url})'
                        ))
        
                # context_menu_items.append((
                #     '[COLOR orange]TRAKT : [/COLOR]VYHLEDAT TITUL', 
                #     f'Container.Update({get_url(action="search", what=media.get("title", ""))})'
                # ))
                
                context_menu_items.append((
                    '[COLOR orange]TRAKT : [/COLOR]ODSTANIT POLOŽKU',
                    f'RunPlugin({get_url(action="trakt_watchlist", category=params["category"], remove=media_id)})'
                ))
                
                listitem.addContextMenuItems(context_menu_items)

                info_tag = listitem.getVideoInfoTag()
                info_tag.setMediaType(media_type)
                info_tag.setTitle(title)
                info_tag.setPlot(plot)

                if year:
                    try:
                        info_tag.setYear(int(year))
                    except (ValueError, TypeError):
                        log(f"TRAKT - Chyba při nastavení roku pro '{title}': Neplatná hodnota '{year}'", xbmc.LOGWARNING)

                info_tag.setGenres(media.get('genres', []))

                if media.get('runtime'):
                    try:
                        info_tag.setDuration(media.get('runtime', 0) * 60)  # Převod minut na sekundy
                    except (ValueError, TypeError):
                        log(f"TRAKT - Chyba při nastavení délky pro '{title}': Neplatná hodnota '{media.get('runtime')}'", xbmc.LOGWARNING)

                if media.get('trailer'):
                    info_tag.setTrailer(media.get('trailer'))

                if media.get('rating'):
                    try:
                        info_tag.setRating(float(media.get('rating', 0)))
                    except (ValueError, TypeError):
                        log(f"TRAKT - Chyba při hodnocení pro '{title}': Neplatná hodnota '{media.get('rating')}'", xbmc.LOGWARNING)

                meta = {
                    'tmdb_id': tmdb_id,
                    'title': media.get('title', title),
                    'year': year,
                    'plot': plot,
                    'poster': artwork.get('poster', ''),
                    'fanart': artwork.get('fanart', ''),
                    'rating': media.get('rating', 0.0),
                    'genres': media.get('genres', []),
                    'media_type': media_type
                }

                item_url = get_url(action='find_sources', meta=json.dumps(meta))

                xbmcplugin.addDirectoryItem(
                    _handle,
                    item_url,
                    listitem,
                    True
                )

            elif params['category'] == 'shows' and 'show' in item:
                media = item['show']
                media_type = 'show'
                media_id = media['ids']['trakt']
                tmdb_id = media['ids'].get('tmdb')
                
                try:
                    translation_url = f'https://api.trakt.tv/{media_type}s/{media_id}/translations/{_addon.getSetting("trakt_language").strip()}'
                    translation_response = _session.get(translation_url, headers=trakt_get_headers(addon=_addon), timeout=10)
                    if translation_response.status_code == 200:
                        translation = translation_response.json()
                        if translation and isinstance(translation, list):
                            title = translation[0].get('title', media.get('title', 'Neznámý název'))
                            plot = translation[0].get('overview', media.get('overview', ''))
                        else:
                            title = media.get('title', 'Neznámý název')
                            plot = media.get('overview', '')
                    else:
                        title = media.get('title', 'Neznámý název')
                        plot = media.get('overview', '')
                except Exception as e:
                    log(f"TRAKT - Chyba při načítání překladu : {str(e)}", xbmc.LOGERROR)
                    title = media.get('title', 'Neznámý název')
                    plot = media.get('overview', '')

                if not title:
                    title = media.get('title', 'Neznámý název')
                
                year = media.get('year', '')
                if year:
                    title = f"{title} ({year})"
                
                artwork = {}

                if isinstance(media.get('images'), dict):
                    images = media['images']
                    if isinstance(images.get('poster'), list) and len(images['poster']) > 0:
                        poster_url = images['poster'][0]
                        artwork['poster'] = f"https://{poster_url}" if not poster_url.startswith('http') else poster_url
                    if isinstance(images.get('fanart'), list) and len(images['fanart']) > 0:
                        fanart_url = images['fanart'][0]
                        artwork['fanart'] = f"https://{fanart_url}" if not fanart_url.startswith('http') else fanart_url
                    artwork['thumb'] = artwork.get('poster', '')
                          
                listitem = xbmcgui.ListItem(label=title)

                if artwork:
                    listitem.setArt(artwork)

                context_menu_items = []
                
                # if media.get('trailer'):
                #     trailer_url = media['trailer']
                #     if 'youtube.com' in trailer_url or 'youtu.be' in trailer_url:
                #         video_id = trailer_url.split('v=')[-1].split('&')[0]
                #         youtube_plugin_url = f'plugin://plugin.video.youtube/play/?video_id={video_id}'
                #         context_menu_items.append((
                #             "[COLOR orange]TRAKT.TV : [/COLOR] PŘEHRÁT TRAILER",
                #             f'PlayMedia({youtube_plugin_url})'
                #         ))    

                if media.get('trailer'):
                    trailer_url = media['trailer']
                    if 'youtube.com' in trailer_url or 'youtu.be' in trailer_url:
                        video_id = trailer_url.split('v=')[-1].split('&')[0]
                        invidious_plugin_url = f'plugin://plugin.video.mau_vidious/?action=play&videoId={video_id}'
        
                        context_menu_items.append((
                            "[COLOR orange]TRAKT : [/COLOR]PŘEHRÁT TRAILER",
                            f'PlayMedia({invidious_plugin_url})'
                        ))

                # context_menu_items.append((
                #     '[COLOR orange]TRAKT : [/COLOR]VYHLEDAT TITUL', 
                #     f'Container.Update({get_url(action="search", what=media.get("title", ""))})'
                # ))
                
                context_menu_items.append((
                    '[COLOR orange]TRAKT : [/COLOR]ODSTANIT POLOŽKU',
                    f'RunPlugin({get_url(action="trakt_watchlist", category=params["category"], remove=media_id)})'
                ))
                
                listitem.addContextMenuItems(context_menu_items)

                info_tag = listitem.getVideoInfoTag()
                info_tag.setMediaType(media_type)
                info_tag.setTitle(title)
                info_tag.setPlot(plot)

                if year:
                    try:
                        info_tag.setYear(int(year))
                    except (ValueError, TypeError):
                        log(f"TRAKT - Chyba při nastavení roku pro '{title}': Neplatná hodnota '{year}'", xbmc.LOGWARNING)

                info_tag.setGenres(media.get('genres', []))

                if media.get('rating'):
                    try:
                        info_tag.setRating(float(media.get('rating', 0)))
                    except (ValueError, TypeError):
                        log(f"TRAKT - Chyba při hodnocení pro '{title}': Neplatná hodnota '{media.get('rating')}'", xbmc.LOGWARNING)

                if media.get('status'):
                    listitem.setProperty('status', media.get('status'))

                meta = {
                    'tmdb_id': tmdb_id,
                    'title': media.get('title', title),
                    'year': year,
                    'plot': plot,
                    'poster': artwork.get('poster', ''),
                    'fanart': artwork.get('fanart', ''),
                    'rating': media.get('rating', 0.0),
                    'genres': media.get('genres', []),
                    'media_type': media_type
                }

                item_url = get_url(action='listing_tmdb_tv', tmdb_id=tmdb_id, meta=json.dumps(meta))

                xbmcplugin.addDirectoryItem(
                    _handle,
                    item_url,
                    listitem,
                    True
                )

        if not _addon.getSetting('trakt_access_token'):
            listitem = xbmcgui.ListItem(label="PŘIPOJIT KE TRAKT.TV ...")
            listitem.setArt({'icon': 'DefaultAddonService.png'})
            xbmcplugin.addDirectoryItem(
                _handle,
                get_url(action='trakt_watchlist', reauth=1),
                listitem,
                False
            )
        
    except Exception as e:
        log(f"TRAKT - Chyba : {str(e)}", xbmc.LOGERROR)
        popinfo("[COLOR orange]TRAKT.TV : [/COLOR]Chyba při načítání", icon=xbmcgui.NOTIFICATION_ERROR)

        traceback.print_exc()
        
    xbmcplugin.setContent(_handle, 'movies' if params.get('category') == 'movies' else 'tvshows')
    xbmcplugin.endOfDirectory(_handle)


def list_seasons(params, addon, handle, session=None):

    global _session, _addon, _handle
    _addon = addon
    _handle = handle
    _session = session or _session
    
    show_id = params['show_id']
    cache_key = f"trakt_show_seasons_{show_id}"
    show_details = load_trakt_cache(cache_key)

    if not show_details:
        show_url = f'https://api.trakt.tv/shows/{show_id}?extended=full,images'
        show_response = _session.get(show_url, headers=trakt_get_headers(addon=_addon), timeout=10)
        
        if show_response.status_code != 200:
            popinfo("[COLOR red]TRAKT.TV : [/COLOR]Chyba při načítání detailu seriálu", icon=xbmcgui.NOTIFICATION_ERROR)
            return
        
        show = show_response.json()
        
        seasons_url = f'https://api.trakt.tv/shows/{show_id}/seasons?extended=full,images,episodes'
        seasons_response = _session.get(seasons_url, headers=trakt_get_headers(addon=_addon), timeout=10)
        
        if seasons_response.status_code != 200:
            popinfo("[COLOR red]TRAKT.TV : [/COLOR]Chyba při načítání sezón", icon=xbmcgui.NOTIFICATION_ERROR)
            return
            
        seasons = seasons_response.json()
        show_details = {'show': show, 'seasons': seasons}
        save_trakt_cache(cache_key, show_details)

    show = show_details['show']
    seasons = show_details['seasons']

    try:
        translation_url = f'https://api.trakt.tv/shows/{show_id}/translations/{_addon.getSetting("trakt_language").strip()}'
        translation_response = _session.get(translation_url, headers=trakt_get_headers(addon=_addon), timeout=10)
        if translation_response.status_code == 200:
            translation = translation_response.json()
            if translation and isinstance(translation, list):
                title = translation[0].get('title', show.get('title', 'Neznámý název'))
            else:
                title = show.get('title', 'Neznámý název')
        else:
            title = show.get('title', 'Neznámý název')
    except Exception:
        title = show.get('title', 'Neznámý název')

    xbmcplugin.setPluginCategory(_handle, f"{title}")
    
    for season in sorted(seasons, key=lambda x: x['number']):
        season_num = season['number']
        if season_num == 0: continue
        episode_count = len(season.get('episodes', []))
        
        listitem = xbmcgui.ListItem(label=f"Sezóna {season_num} ({episode_count} epizod)")
        
        artwork = {}

        if isinstance(season.get('images'), dict):
            images = season['images']
            if isinstance(images.get('poster'), list) and len(images['poster']) > 0:
                poster_url = images['poster'][0]
                artwork['poster'] = f"https://{poster_url}" if not poster_url.startswith('http') else poster_url
            artwork['thumb'] = artwork.get('poster', '')
        if artwork:
            listitem.setArt(artwork)
            
        info_tag = listitem.getVideoInfoTag()
        info_tag.setMediaType('season')
        info_tag.setTitle(f"Sezóna {season_num}")

        try:
            info_tag.setSeason(int(season_num))
        except (ValueError, TypeError):
            log(f"TRAKT - Chyba při nastavení čísla sezóny: Neplatná hodnota '{season_num}'", xbmc.LOGWARNING)
        try:
            info_tag.setEpisode(int(episode_count))
        except (ValueError, TypeError):
            log(f"TRAKT - Chyba při nastavení počtu epizod: Neplatná hodnota '{episode_count}'", xbmc.LOGWARNING)

        url = get_url(action='trakt_watchlist', show_id=show_id, season=season_num, series_title=show.get('title'), category='shows')

        xbmcplugin.addDirectoryItem(
            _handle,
            url,
            listitem,
            True
        )

    xbmcplugin.setContent(_handle, 'seasons')
    xbmcplugin.endOfDirectory(_handle)


def list_episodes(params, addon, handle, session=None):

    global _session, _addon, _handle
    _addon = addon
    _handle = handle
    _session = session or _session

    show_id = params['show_id']
    season_num = params['season']
    series_title = params['series_title']

    xbmcplugin.setPluginCategory(_handle, f"{_addon.getAddonInfo('name')} / Sezóna {season_num}")

    trakt_client_id = _addon.getSetting('trakt_client_id').strip()

    if not trakt_client_id:
        popinfo("[COLOR red]TRAKT.TV : [/COLOR]Pro připojení je třeba vyplnit CLIENT ID v nastavení", sound=True)
        _addon.openSettings()
        xbmcplugin.endOfDirectory(_handle)
        return

    if not _addon.getSetting('trakt_access_token').strip():
        trakt_refresh_token(addon=_addon, session=_session)
    
    tmdb_show_id = get_tmdb_id(show_id, 'show')

    if not tmdb_show_id:
        popinfo("[COLOR red]TRAKT.TV : [/COLOR]Nepodařilo se získat TMDB ID pro seriál", icon=xbmcgui.NOTIFICATION_ERROR)
        return

    cache_key = f"trakt_season_episodes_{show_id}_{season_num}"
    episodes_data = load_trakt_cache(cache_key)

    if not episodes_data:
        seasons_url = f"https://api.trakt.tv/shows/{show_id}/seasons/{season_num}?extended=full,images,episodes"
        seasons_response = _session.get(seasons_url, headers=trakt_get_headers(addon=_addon), timeout=10)
        seasons_response = handle_trakt_401(seasons_url, addon=_addon, session=_session)
        
        if not seasons_response or seasons_response.status_code != 200:
            return
            
        episodes_data = seasons_response.json()
        save_trakt_cache(cache_key, episodes_data)
        
    episodes = episodes_data if isinstance(episodes_data, list) else []
    
    today = datetime.now().date()
    
    for episode in episodes:
        ep_num = episode.get('number')
        
        cache_key_ep = f"trakt_episode_details_{show_id}_{season_num}_{ep_num}"
        ep_data = load_trakt_cache(cache_key_ep)
        
        if not ep_data:
            episode_url = f"https://api.trakt.tv/shows/{show_id}/seasons/{season_num}/episodes/{ep_num}?extended=full,images"
            episode_response = _session.get(episode_url, headers=trakt_get_headers(addon=_addon), timeout=10)
            
            if episode_response.status_code != 200:
                log(f"TRAKT - Chyba při načítání epizody S{season_num}E{ep_num}: {episode_response.status_code}", xbmc.LOGERROR)
                continue
                
            ep_data = episode_response.json()
            save_trakt_cache(cache_key_ep, ep_data)
        
        ep_title = ep_data.get('title', 'Neznámý název')
        ep_air_date = ep_data.get('first_aired')
        ep_plot = ep_data.get('overview', '')
        ep_rating = ep_data.get('rating', 0)
        ep_runtime = ep_data.get('runtime', 0)
        
        cache_key_translation = f"trakt_translation_{show_id}_{season_num}_{ep_num}"
        translations_data = load_trakt_cache(cache_key_translation)
        
        if not translations_data:
            try:
                translation_url = f"https://api.trakt.tv/shows/{show_id}/seasons/{season_num}/episodes/{ep_num}/translations/{_addon.getSetting('trakt_language').strip()}"
                translation_response = _session.get(translation_url, headers=trakt_get_headers(addon=_addon), timeout=10)
                if translation_response.status_code == 200:
                    translations_data = translation_response.json()
                    if translations_data:
                        save_trakt_cache(cache_key_translation, translations_data)
            except Exception as e:
                log(f"TRAKT - Chyba při načítání překladu epizody: {str(e)}", xbmc.LOGERROR)
                
        if translations_data and isinstance(translations_data, list):
            ep_title = translations_data[0].get('title', ep_title)
            ep_plot = translations_data[0].get('overview', ep_plot)
            
        air_date_str = ""
        is_future = False
        if ep_air_date:
            try:
                date_part = ep_air_date.split('T')[0]
                year, month, day = list(map(int, date_part.split('-')))
                air_date_obj = date(year, month, day)
                
                if air_date_obj > today:
                    is_future = True
                    air_date_str = f" ({day:02d}.{month:02d}.{year})"
            except Exception as e:
                log(f"TRAKT - Chyba při zpracování data {ep_air_date}: {str(e)}", xbmc.LOGERROR)
                air_date_str = " [Datum neznámé]"

        label = f"{ep_title}"
        if is_future:
            label += f" [COLOR red]{air_date_str}[/COLOR]"
        elif air_date_str:
            label += f" [COLOR gray]{air_date_str}[/COLOR]"

        listitem = xbmcgui.ListItem(label=label)
        
        artwork = {}

        if isinstance(ep_data.get('images'), dict):
            images = ep_data['images']
            if 'screenshot' in images and isinstance(images['screenshot'], dict):
                screenshot = images['screenshot'].get('thumb', '') or images['screenshot'].get('medium', '') or images['screenshot'].get('full', '')
                if screenshot:
                    artwork['thumb'] = f"https://{screenshot}" if not screenshot.startswith('http') else screenshot
        if artwork:
            listitem.setArt(artwork)
            
        info_tag = listitem.getVideoInfoTag()
        info_tag.setMediaType('episode')
        info_tag.setTitle(label)
        info_tag.setPlot(ep_plot)

        try:
            info_tag.setSeason(int(season_num))
        except (ValueError, TypeError):
            log(f"TRAKT - Chyba při nastavení čísla sezóny pro epizodu '{label}': Neplatná hodnota '{season_num}'", xbmc.LOGWARNING)
        try:
            info_tag.setEpisode(int(ep_num))
        except (ValueError, TypeError):
            log(f"TRAKT - Chyba při nastavení čísla epizody pro '{label}': Neplatná hodnota '{ep_num}'", xbmc.LOGWARNING)
        if ep_runtime:
            try:
                info_tag.setDuration(ep_runtime * 60)
            except (ValueError, TypeError):
                log(f"TRAKT - Chyba při nastavení délky pro '{label}': Neplatná hodnota '{ep_runtime}'", xbmc.LOGWARNING)
        try:
            info_tag.setRating(float(ep_rating))
        except (ValueError, TypeError):
            log(f"TRAKT - Chyba při nastavení hodnocení pro '{label}': Neplatná hodnota '{ep_rating}'", xbmc.LOGWARNING)
        if ep_air_date:
            info_tag.setFirstAired(ep_air_date[:10])
        
        meta = {
            'tmdb_id': tmdb_show_id,
            'title': f"{series_title} S{int(season_num):02d}E{int(ep_num):02d}",
            'tv_show_title': series_title,
            'season': int(season_num),
            'episode': int(ep_num),
            'plot': ep_plot,
            'rating': ep_rating,
            'media_type': 'episode'
        }
        
        xbmcplugin.addDirectoryItem(
            _handle,
            get_url(action='find_sources', meta=json.dumps(meta)),
            listitem,
            True
        )

    xbmcplugin.addSortMethod(_handle, xbmcplugin.SORT_METHOD_EPISODE)
    xbmcplugin.endOfDirectory(_handle)


# =======================     T R A K T . T V   :   AUTHENTICATE     ==================================================== #
# ======================================================================================================================= #


def trakt_authenticate(addon, session=None):

    global _session, _addon
    _addon = addon
    _session = session or _session

    trakt_client_id = _addon.getSetting('trakt_client_id').strip()
    trakt_client_secret = _addon.getSetting('trakt_client_secret').strip()
    
    if not trakt_client_id or not trakt_client_secret:
        popinfo("[COLOR orange]TRAKT.TV : [/COLOR]Pro připojení je třeba vyplnit CLIENT ID a CLIENT SECRET v nastavení", sound=True)
        _addon.openSettings()
        return False
    
    data = {
        'client_id': trakt_client_id
    }

    try:
        response = _session.post(TRAKT_DEVICE_CODE_URL, data=data, timeout=30)
        response.raise_for_status()
        device_data = response.json()
        dialog = xbmcgui.Dialog()

        dialog.textviewer(
            '|   TRAKT.TV CONNECT  :  OVĚŘENÍ ÚČTU   |',
            f"\n"
            f" 1.   OTEVŘETE URL VE WEBOVÉM PROHLÍŽEČI        :     [B]{device_data['verification_url']}[/B]\n\n"
            f" 2.   NA WEBOVÉ STRÁNCE ZADEJTE TENTO KÓD    :     [B]{device_data['user_code']}[/B]\n\n"
            f"\n"
            f"========================================\n"
            f"    [B][     TENTO KÓD JE PLATNÝ   {device_data['expires_in']//60} MINUT    ][/B]\n"
            f"    [B][COLOR orange][    PO OVĚŘENÍ STISKNĚTE  ESC/ZPĚT    ][/COLOR][/B]\n"
            f"========================================\n"
        )

        data = {
            'client_id': trakt_client_id,
            'client_secret': trakt_client_secret,
            'code': device_data['device_code']
        }
        
        interval = device_data['interval']
        expires_in = device_data['expires_in']
        start_time = time.time()
        progress = xbmcgui.DialogProgress()
        progress.create('TRAKT.TV OVĚŘENÍ', 'Čekání na uživatelské ověření ...')
        
        while (time.time() - start_time) < expires_in:
            if progress.iscanceled():
                break
                
            progress.update(int(((time.time() - start_time) / expires_in) * 100))
            
            try:
                response = _session.post(TRAKT_DEVICE_TOKEN_URL, data=data, timeout=30)
                
                if response.status_code == 200:
                    token_data = response.json()
                    _addon.setSetting('trakt_access_token', token_data['access_token'])
                    _addon.setSetting('trakt_refresh_token', token_data['refresh_token'])
                    progress.close()
                    popinfo("[B][COLOR orange]TRAKT.TV : [/COLOR][/B]Úspěšně připojeno !")
                    return True
                
                elif response.status_code == 400:
                    time.sleep(interval)
                
                else:
                    response.raise_for_status()
                    
            except Exception as e:
                log(f"TRAKT - Authentication error : {str(e)}", xbmc.LOGERROR)
                break
        
        progress.close()
        popinfo("[COLOR orange]TRAKT.TV : [/COLOR]Čas na ověření vypršel nebo došlo k chybě", icon=xbmcgui.NOTIFICATION_ERROR)
        
    except Exception as e:
        log(f"TRAKT - Authentication failed : {str(e)}", xbmc.LOGERROR)
        popinfo("[COLOR orange]TRAKT.TV : [/COLOR]Chyba při připojování ke TRAKT.TV", icon=xbmcgui.NOTIFICATION_ERROR)
    
    return False


def trakt_refresh_token(addon, session=None):

    global _session, _addon
    _addon = addon
    _session = session or _session

    trakt_client_id = _addon.getSetting('trakt_client_id').strip()
    trakt_client_secret = _addon.getSetting('trakt_client_secret').strip()
    trakt_refresh_token = _addon.getSetting('trakt_refresh_token').strip()

    if not all([trakt_client_id, trakt_client_secret, trakt_refresh_token]):
        log("TRAKT - Chybí údaje pro refresh token", xbmc.LOGERROR)
        return False

    data = {
        'client_id': trakt_client_id,
        'client_secret': trakt_client_secret,
        'refresh_token': trakt_refresh_token,
        'grant_type': 'refresh_token',
        'redirect_uri': 'urn:ietf:wg:oauth:2.0:oob'
    }

    try:
        response = _session.post(TRAKT_TOKEN_URL, data=data, timeout=30)
        log(f"TRAKT - Refresh token response : {response.status_code} - {response.text}", xbmc.LOGDEBUG)

        if response.status_code == 401:
            _addon.setSetting('trakt_access_token', '')
            _addon.setSetting('trakt_refresh_token', '')
            popinfo("[COLOR orange]TRAKT.TV : [/COLOR]Přihlášení vypršelo, proveďte novou autentizaci", icon=xbmcgui.NOTIFICATION_WARNING)
            return False

        response.raise_for_status()
        token_data = response.json()

        _addon.setSetting('trakt_access_token', token_data['access_token'])
        _addon.setSetting('trakt_refresh_token', token_data['refresh_token'])
        log("TRAKT - Token úspěšně obnoven", xbmc.LOGINFO)
        return True

    except Exception as e:
        log(f"TRAKT - Chyba při refreshi tokenu : {str(e)}", xbmc.LOGERROR)
        return False


# =======================     T R A K T . T V   :   HEADERS     ========================================================= #
# ======================================================================================================================= #


def trakt_get_headers(addon, write=False):

    global _addon
    _addon = addon

    headers = {
        'Content-Type': 'application/json',
        'trakt-api-version': '2',
        'trakt-api-key': _addon.getSetting('trakt_client_id').strip(),
        'Accept-Language': _addon.getSetting('trakt_language').strip() or 'cs'
    }

    if write:
        access_token = _addon.getSetting('trakt_access_token').strip()
        if not access_token:
            if '_session' in globals() and _session is not None:
                try:
                    trakt_refresh_token(addon=_addon, session=_session)
                    access_token = _addon.getSetting('trakt_access_token').strip()
                except Exception as e:
                    log(f"TRAKT - Chyba při pokusu o refresh tokenu v get_headers : {e}", xbmc.LOGWARNING)
            else:
                log("TRAKT - Chybí session pro obnovení tokenu v get_headers", xbmc.LOGWARNING)
        
        if access_token:
            headers['Authorization'] = f'Bearer {access_token}'
            log("TRAKT - Headers s autentizací připraveny", xbmc.LOGDEBUG)
        else:
            log("TRAKT - Headers bez autentizace ( chybí token )", xbmc.LOGWARNING)
    else:
        log("TRAKT - Headers pro čtení připraveny", xbmc.LOGDEBUG)
    
    return headers


def handle_trakt_401(url, addon, session=None, method='GET', data=None):

    global _session, _addon
    _addon = addon
    _session = session or _session

    for attempt in range(2):
        headers = trakt_get_headers(addon=_addon, write=True)
        response = _session.request(
            method,
            url,
            headers=headers,
            json=data,
            timeout=15
        )
        
        log(f"TRAKT - API attempt {attempt} : {response.status_code}", xbmc.LOGDEBUG)
        
        if response.status_code != 401:
            return response
            
        if not trakt_refresh_token(addon=_addon, session=_session):
            break

    popinfo("[COLOR orange]TRAKT.TV : [/COLOR]Vyžaduje nové přihlášení ...", icon=xbmcgui.NOTIFICATION_WARNING)
    trakt_authenticate(addon=_addon, session=_session)
    return None


# =======================     T R A K T . T V   :   SCROBBLING     ====================================================== #
# ======================================================================================================================= #


def trakt_scrobble(media_id, media_type, progress, action, _addon, _session):

    if media_id is None or media_type not in ['movie', 'episode']:
        log(f"TRAKT - Chybné media_id nebo media_type pro scrobbling : {media_type}", xbmc.LOGWARNING)
        return

    url = f"https://api.trakt.tv/scrobble/{action}"
    
    data = {
        media_type: {
            "ids": {
                "trakt": media_id
            }
        },
        "progress": progress
    }
    
    # =========================== #
    #   LOGIKA  ( RETRY )  429    #
    # =========================== #

    max_retries = 3
    attempt = 0
    
    while attempt < max_retries:
        attempt += 1
        
        log(f"TRAKT - Odesílám '{action}' pro ID {media_id}, Typ: {media_type}, Progress: {progress:.2f}% (Pokus {attempt}/{max_retries})", xbmc.LOGINFO)

        try:
            headers = trakt_get_headers(addon=_addon, write=True)
            response = _session.post(url, headers=headers, json=data, timeout=15)

            # --- Zjednodušené ošetření 401 přímo zde ---
            if response.status_code == 401 and attempt == 1:
                log("TRAKT - Scrobble selhal (401), zkouším obnovit token ...", xbmc.LOGINFO)
                if trakt_refresh_token(addon=_addon, session=_session):
                    log("TRAKT - Token obnoven, opakuji scrobble požadavek", xbmc.LOGINFO)
                    headers = trakt_get_headers(addon=_addon, write=True) # Znovu načíst hlavičky s novým tokenem
                    response = _session.post(url, headers=headers, json=data, timeout=15)
                else:
                    log("TRAKT - Obnovení tokenu selhalo, scrobbling se neprovede", xbmc.LOGERROR)
                    break # Ukončit cyklus, nemá smysl pokračovat
            
            log(f"TRAKT - Scrobble API odpověď ({action}): {response.status_code}", xbmc.LOGINFO)

            if response.status_code == 201:
                log(f"TRAKT - Scrobbling '{action}' úspěšný pro ID {media_id}", xbmc.LOGINFO)
                return 
            
            # --- SCROBBLING : RATE LIMIT (429)

            elif response.status_code == 429:
                try:
                    retry_after_s = int(response.headers.get('Retry-After', 2))

                except (ValueError, TypeError):
                    retry_after_s = 2
                
                if attempt < max_retries:
                    log(f"TRAKT - CODE 429 Rate Limit!  Čekám {retry_after_s}s. Pokus {attempt}/{max_retries}.", xbmc.LOGWARNING)
                    xbmc.sleep(retry_after_s * 1000)
                else:
                    log(f"TRAKT - CODE 429 Retry!  Selhalo po {max_retries} pokusech. Scrobbling '{action}' přeskočen", xbmc.LOGERROR)
                    break

            else:
                log(f"TRAKT - Chyba při scrobbling '{action}' (ID {media_id}): {response.status_code} - {response.text}", xbmc.LOGERROR)
                break 

        except Exception as e:
            log(f"TRAKT - Chyba při volání scrobble API '{action}' (ID {media_id}): {str(e)}", xbmc.LOGERROR)
            break


# =======================     T R A K T . T V   :   SCROBBLING  HELPERS     ============================================= #
# ======================================================================================================================= #


def trakt_scrobble_start(media_id, media_type, addon, session):
    trakt_scrobble(media_id, media_type, 0, 'start', addon, session)


def trakt_scrobble_pause(media_id, media_type, progress, addon, session):
    trakt_scrobble(media_id, media_type, progress, 'pause', addon, session)


def trakt_scrobble_stop(media_id, media_type, progress, addon, session):
    trakt_scrobble(media_id, media_type, progress, 'stop', addon, session)


# =======================     T R A K T    M O N I T O R  -  SCROBBLING   =============================================== #
# ======================================================================================================================= #


class KodiPlayerMonitor(xbmc.Player):

    """
    TRAKT.TV :: SCROBLING MONITOR
    -- Odesílá "YOU ARE WATCHING" a další data na web TRAKT.TV
    """

    def __init__(self, *args, **kwargs):
        super().__init__()
        self.session = kwargs.get('session')
        self.addon = kwargs.get('addon')
        self.save_playback_history_func = kwargs.get('save_playback_history_func')
        self.scrobbling_in_progress = False
        self.media_id = None
        self.media_type = None
        log("MONITOR - Monitor instance initialized", xbmc.LOGINFO)

    def onAVStarted(self):
        try:
            current_path = self.getPlayingFile()
            log(f"MONITOR - Playback started ... Path : {current_path}", xbmc.LOGDEBUG)

            parsed_url = urlparse(current_path)
            query_params = dict(parse_qsl(parsed_url.query))

            try:
                meta_json = query_params.get('playback_meta')
                link = query_params.get('playback_link')
                if meta_json and link and self.save_playback_history_func:
                    meta = json.loads(meta_json)
                    self.save_playback_history_func(meta, link)
                    log("MONITOR - Úspěšně uloženo do playback historie", xbmc.LOGINFO)
            except Exception as history_e:
                log(f"MONITOR - Chyba při ukládání playback historie : {history_e}", xbmc.LOGERROR)

            if self.addon.getSetting('enable_trakt_scrobbling') != 'true':
                log("MONITOR - Scrobbling je v nastavení vypnut", xbmc.LOGINFO)
                return

            new_trakt_id = query_params.get('trakt_id')
            new_media_type = query_params.get('media_type')

            if not new_trakt_id or not new_media_type:
                log("MONITOR - Chybí 'trakt_id' nebo 'media_type' v URL. Nelze scrobblovat.", xbmc.LOGWARNING)
                return

            if self.scrobbling_in_progress and self.media_id != new_trakt_id:
                log(f"MONITOR - Detekováno nové video (ID: {new_trakt_id}) během přehrávání starého (ID: {self.media_id}).", xbmc.LOGINFO)
                log(f"MONITOR - Vynucuji 'stop' pro předchozí video (ID: {self.media_id}).", xbmc.LOGINFO)
                trakt_scrobble_stop(self.media_id, self.media_type, 95, self.addon, self.session)

            log(f"MONITOR - Nastavuji a spouštím scrobble pro ID {new_trakt_id}, Typ: {new_media_type}", xbmc.LOGINFO)
            self.media_id = new_trakt_id
            self.media_type = new_media_type
            self.scrobbling_in_progress = True
            trakt_scrobble_start(self.media_id, self.media_type, self.addon, self.session)

        except Exception as e:
            log(f"MONITOR - Kritická chyba v onAVStarted : {e}\n{traceback.format_exc()}", xbmc.LOGERROR)
            self.scrobbling_in_progress = False
            self.media_id = None
            self.media_type = None

    def onPlayBackPaused(self):
        if not self.scrobbling_in_progress or self.addon.getSetting('enable_trakt_scrobbling') != 'true':
            return

        log(f"MONITOR - Trakt onPlayBackPaused voláno pro ID {self.media_id}", xbmc.LOGINFO)
        try:
            progress = 0.0
            if self.isPlaying():
                current_time = self.getTime()
                total_time = self.getTotalTime()
                if total_time > 0:
                    progress = max(0, min(100, (current_time / total_time * 100)))
            
            trakt_scrobble_pause(self.media_id, self.media_type, progress, self.addon, self.session)
            log(f"MONITOR - Scrobble 'pause' odeslán. Progress : {progress:.2f}%", xbmc.LOGINFO)
        except Exception as e:
            log(f"MONITOR - Chyba v onPlayBackPaused : {e}", xbmc.LOGERROR)

    def onPlayBackResumed(self):
        if not self.scrobbling_in_progress or self.addon.getSetting('enable_trakt_scrobbling') != 'true':
            return

        log(f"MONITOR - Trakt onPlayBackResumed voláno pro ID {self.media_id}", xbmc.LOGINFO)
        try:
            trakt_scrobble_start(self.media_id, self.media_type, self.addon, self.session)
            log("MONITOR - Scrobble 'resume' (start) odeslán", xbmc.LOGINFO)
        except Exception as e:
            log(f"MONITOR - Chyba v onPlayBackResumed : {e}", xbmc.LOGERROR)

    def onPlayBackStopped(self):
        if not self.scrobbling_in_progress:
            return

        log(f"MONITOR - Trakt onPlayBackStopped voláno pro ID {self.media_id}", xbmc.LOGINFO)
        try:
            progress = 0.0
            try:
                current_time = self.getTime()
                total_time = self.getTotalTime()
                if total_time > 0:
                    progress = max(0, min(100, (current_time / total_time * 100)))
            except Exception:
                log(f"MONITOR - Nelze získat čas v onPlayBackStopped, progress bude 0", xbmc.LOGWARNING)
            
            if self.addon.getSetting('enable_trakt_scrobbling') == 'true':
                trakt_scrobble_stop(self.media_id, self.media_type, progress, self.addon, self.session)
                log(f"MONITOR - Scrobble 'stop' odeslán. Progress: {progress:.2f}%", xbmc.LOGINFO)
        except Exception as e:
            log(f"MONITOR - Chyba v onPlayBackStopped: {e}\n{traceback.format_exc()}", xbmc.LOGERROR)
        finally:
            log("MONITOR - Resetuji stav monitoru po onPlayBackStopped", xbmc.LOGDEBUG)
            self.scrobbling_in_progress = False
            self.media_id = None
            self.media_type = None

    def onPlayBackEnded(self):
        if not self.scrobbling_in_progress:
            return

        log(f"MONITOR - Trakt onPlayBackEnded voláno pro ID {self.media_id}", xbmc.LOGINFO)
        try:
            if self.addon.getSetting('enable_trakt_scrobbling') == 'true':
                trakt_scrobble_stop(self.media_id, self.media_type, 100, self.addon, self.session)
                log("MONITOR - Scrobble 'stop' (ended) odeslán. Progress: 100%", xbmc.LOGINFO)
        except Exception as e:
            log(f"MONITOR - Chyba v onPlayBackEnded: {e}\n{traceback.format_exc()}", xbmc.LOGERROR)
        finally:
            log("MONITOR - Resetuji stav monitoru po onPlayBackEnded.", xbmc.LOGDEBUG)
            self.scrobbling_in_progress = False
            self.media_id = None
            self.media_type = None
