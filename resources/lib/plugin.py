# -*- coding: utf-8 -*-


# ========================================================================= #
#
#   Module:  plugin
#   Author:  Mau!X ER
#   Created on:  20.10.2025
#
#   Aditional integrated modules:
#
#     - series_manager.py
#     - tmdb_account.py
#     - prehrajto.py
#     - speedtest.py
#     - utils.py
#     - files.py
#     - trakt.py
#     - tmdb.py
#     - csfd.py
#
#   License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
# ========================================================================= #




import xbmc
import xbmcvfs
import xbmcgui
import xbmcaddon
import xbmcplugin

import os
import re
import sys
import ast
import json
import time
import datetime
import requests
import threading
import traceback
import unicodedata
import urllib.parse

from bs4 import BeautifulSoup
from urllib.parse import urlencode, quote, urlparse, parse_qsl


from resources.lib.utils import get_url, log, encode, clean_title_for_tmdb, safe_get, safe_post
from resources.lib.series_manager import SeriesManager
from resources.lib.prehrajto import PrehrajTo
from resources.lib.csfd import CSFD
from resources.lib.tmdb import TMDB
from resources.lib import tmdb_account
from resources.lib import speedtest
from resources.lib import trakt
from resources.lib import files




# ================================================================================================================================ #
#                                             --- CORE KODI INITIALIZATION ---                                                     #
# ================================================================================================================================ #

_url = sys.argv[0]
_handle = int(sys.argv[1])

addon = xbmcaddon.Addon(id='plugin.video.play_to')
profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))

# ================================================================================================================================ #
#                                            --- PLAYBACK STATE MANAGEMENT ---                                                     #
# ================================================================================================================================ #

playback_started_internally = False
main_window = xbmcgui.Window(10000)
set_playback_callback = None

def set_playback_started_flag():
    global playback_started_internally
    playback_started_internally = True
    main_window.setProperty("playto.playback.active", "true")
    log("MAIN - Playback started internally flag set to TRUE & property set", xbmc.LOGINFO)

def playback_was_active():
    return main_window.getProperty("playto.playback.active") == "true"

def clear_playback_flag():
    main_window.clearProperty("playto.playback.active")
    global playback_started_internally
    playback_started_internally = False
    log("MAIN - Cleared playback.active property", xbmc.LOGINFO)

# ================================================================================================================================ #
#                                            --- DEFAULT PATHS & SETTING IDS ---                                                   #
# ================================================================================================================================ #

SETTING_ID_IP_CACHE_DIR = 'ip_cache_dir'
SETTING_ID_PLAYBACK_DIR = 'playback_dir'
SETTING_ID_HISTORY_DIR = 'history_dir'
SETTING_ID_DOWNLOAD_DIR = 'download'
SETTING_ID_LIBRARY_DIR = 'library_path'
SETTING_ID_SHARED_CACHE_DIR = 'shared_cache_path'
SETTING_ID_CSFD_CACHE_DIR = 'csfd_cache_path'
SETTING_ID_SERIES_DB_DIR = 'series_db'
SETTING_ID_WATCHED_DB_DIR = 'watched_db'

DEFAULT_IP_CACHE_DIR = "special://userdata/PLAY-DATA/CACHE-IPSET/"
DEFAULT_PLAYBACK_DIR = "special://userdata/PLAY-DATA/PLAYBACK/"
DEFAULT_HISTORY_DIR = "special://userdata/PLAY-DATA/HISTORY/"
DEFAULT_SHARED_CACHE_DIR = "special://userdata/PLAY-DATA/CACHE-SHARED/"
DEFAULT_CSFD_CACHE_DIR = "special://userdata/PLAY-DATA/CACHE-CSFD/"
DEFAULT_SERIES_DB_DIR = "special://userdata/Database/PLAY-BASE/TV-SERIES/"
DEFAULT_WATCHED_DB_DIR = "special://userdata/Database/PLAY-BASE/TV-WATCHED/"
DEFAULT_LIBRARY_DIR = "special://userdata/Database/PLAY-BASE/LIBRARY/"
DEFAULT_DOWNLOAD_DIR = "special://userdata/PLAY-LOAD/"

# ================================================================================================================================ #
#                                           --- ENVIRONMENT SETUP (DIRS & FILES) ---                                               #
# ================================================================================================================================ #

def _get_path_and_ensure_dir(setting_id, default_special_path):

    path_setting = addon.getSetting(setting_id)
    final_path_str = path_setting.strip() or default_special_path
    translated_path = xbmcvfs.translatePath(final_path_str)

    if translated_path and not xbmcvfs.exists(translated_path):
        try:
            xbmcvfs.mkdirs(translated_path)
            log(f"PLUGIN - Dynamicky vytvořen adresář ({setting_id}): {translated_path}", xbmc.LOGINFO)
            return translated_path
        except Exception as e:
            log(f"PLUGIN - Chyba při dynamickém vytváření adresáře {translated_path}: {e}", xbmc.LOGERROR)
            return None

    if translated_path == xbmcvfs.translatePath(addon.getAddonInfo('profile')) and not xbmcvfs.exists(translated_path):
        log(f"PLUGIN - Kritická chyba: Nelze zajistit existenci profilového adresáře!", xbmc.LOGERROR)
        return None

    return translated_path if translated_path else None


try:
    if not xbmcvfs.exists(profile):
        xbmcvfs.mkdirs(profile)
        log(f"PLUGIN - Vytvořen adresář profilu: {profile}", xbmc.LOGINFO)
except Exception as profile_e:
    log(f"PLUGIN - Chyba při vytváření adresáře profilu: {profile_e}", xbmc.LOGERROR)


cache_file_path = None
playback_path = None
history_path = None


try:
    ip_cache_dir = _get_path_and_ensure_dir(SETTING_ID_IP_CACHE_DIR, DEFAULT_IP_CACHE_DIR)
    playback_dir = _get_path_and_ensure_dir(SETTING_ID_PLAYBACK_DIR, DEFAULT_PLAYBACK_DIR)
    history_dir = _get_path_and_ensure_dir(SETTING_ID_HISTORY_DIR, DEFAULT_HISTORY_DIR)

    cache_file_path = os.path.join(ip_cache_dir, 'IP.CACHE') if ip_cache_dir else None
    playback_path = os.path.join(playback_dir, 'PLAYBACK.JSON') if playback_dir else None
    history_path = os.path.join(history_dir, 'HISTORY.TXT') if history_dir else None

    essential_files = [cache_file_path, playback_path, history_path]
    for file_p in essential_files:
        if file_p and not xbmcvfs.exists(file_p):
            try:
                dir_name = os.path.dirname(file_p)
                if not xbmcvfs.exists(dir_name):
                     log(f"PLUGIN - Opravuji chybějící nadřazený adresář pro {file_p}", xbmc.LOGWARNING)
                     xbmcvfs.mkdirs(dir_name)

                file_handle = xbmcvfs.File(file_p, 'w')
                if file_p.lower().endswith('.json'):
                    file_handle.write('[]')
                file_handle.close()
                log(f"PLUGIN - Vytvořen chybějící soubor : {file_p}", xbmc.LOGINFO)
            except Exception as fe:
                log(f"PLUGIN - Chyba při vytváření souboru {file_p}: {fe}\n{traceback.format_exc()}", xbmc.LOGERROR)

except Exception as path_init_error:
     log(f"PLUGIN - CRITICAL inicializaci cest/souborů : {path_init_error}\n{traceback.format_exc()}", xbmc.LOGERROR)

# ================================================================================================================================ #
#                                                 --- INSTANCE MANAGERS ---                                                        #
# ================================================================================================================================ #

session = requests.Session()
series_manager = SeriesManager(addon, profile)
csfd_instance = CSFD(addon)
GLOBAL_TRAKT_MONITOR = None

# ================================================================================================================================ #
#                                             --- ADDON SETTINGS ---                                                   #
# ================================================================================================================================ #

show_size = addon.getSettingBool('show_size')
show_speed_info = addon.getSettingBool('show_speed_info')
show_duration_time = addon.getSettingBool('show_duration_time')
show_tmdb_rating = addon.getSettingBool('show_tmdb_rating')
enable_trakt_scrobbling = addon.getSettingBool('enable_trakt_scrobbling')

ls = int(addon.getSetting('ls') or '50')
max_pages = int(addon.getSetting('max_pages') or '2')
search_pages = int(addon.getSetting('search_pages') or '2')
search_ls = int(addon.getSetting('search_ls') or '56')
api_key = addon.getSetting('api_key').strip()

# ================================================================================================================================ #
#                                             --- CACHE & TMDB CONFIGURATION ---                                                   #
# ================================================================================================================================ #

try:
    CACHE_TTL_HOURS = int(addon.getSetting('tmdb_cache_ttl') or '24')
    if CACHE_TTL_HOURS <= 0: CACHE_TTL_HOURS = 24
except ValueError:
    CACHE_TTL_HOURS = 24


VIEW_MODES = {
    'list': 50,
    'poster': 51,
    'shift': 52,
    'infowall': 53,
    'widelist': 54,
    'wall': 55,
    'banner': 56,
    'fanart': 57,
    'bigbanner': 58,
    'lowlist': 59,
    'gallery': 60,
    'posterinfolist': 61,
    'labels': 62,
    'submenu': 63,
    'mediainfowall': 64,
    'basicmediainfo': 65,
    'playlistinfolist': 66,
    'mediainfolist': 67,
    'largesquarerow': 68,
    'veslasquarewall': 69,
    'largewidewall': 70,
    'posterwall': 71,
    'largeposterlist': 72
}




# =======================     D E P E N D E N C Y   :   CACHE     ======================================================= #
# ======================================================================================================================= #


def _get_cache_dir():
    shared_cache_setting = addon.getSetting(SETTING_ID_SHARED_CACHE_DIR).strip()

    default_shared_path = DEFAULT_SHARED_CACHE_DIR
    cache_base_path_str = shared_cache_setting if shared_cache_setting else default_shared_path
    cache_base_path = xbmcvfs.translatePath(cache_base_path_str)
    cache_root_path = os.path.join(cache_base_path, 'PLUGIN_CACHE')

    if not xbmcvfs.exists(cache_root_path):
        try:
            xbmcvfs.mkdirs(cache_root_path)
            log(f"CACHE - Vytvořen cache adresář: {cache_root_path}", xbmc.LOGINFO)
        except Exception as e:
            log(f"CACHE - Chyba při vytváření cache adresáře {cache_root_path}: {e}", xbmc.LOGERROR)
            fallback_path_str = 'special://profile/addon_data/' + addon.getAddonInfo('id') + '/PLUGIN_CACHE/'
            fallback_path = xbmcvfs.translatePath(fallback_path_str)

            if not xbmcvfs.exists(fallback_path):
                try:
                    xbmcvfs.mkdirs(fallback_path)
                    cache_root_path = fallback_path
                except Exception as e2:
                     log(f"CACHE - Chyba při vytváření fallback cache adresáře {fallback_path}: {e2}", xbmc.LOGERROR)
                     return None
            else:
                 cache_root_path = fallback_path

    return cache_root_path


def load_cache(cache_name, ttl_hours=None):
    current_ttl_hours = ttl_hours if ttl_hours is not None else CACHE_TTL_HOURS

    if not isinstance(current_ttl_hours, (int, float)) or current_ttl_hours <= 0:
        log(f"CACHE - Neplatné TTL ({current_ttl_hours}) pro '{cache_name}', použije se výchozí 1 hodina.", xbmc.LOGWARNING)
        current_ttl_hours = 1

    cache_dir = _get_cache_dir()

    if not cache_dir:
         log(f"CACHE - Nelze získat cache adresář pro '{cache_name}'.", xbmc.LOGERROR)
         return None

    cache_path = os.path.join(cache_dir, f"{cache_name}.json")
    file_handle = None
    cache_expired = False

    if xbmcvfs.exists(cache_path):
        try:
            file_handle = xbmcvfs.File(cache_path, 'r')
            content = file_handle.read()

            if not content:
                 log(f"CACHE - Cache soubor '{cache_name}' je prázdný. Mažu...", xbmc.LOGWARNING)
                 xbmcvfs.delete(cache_path)
                 return None

            data = json.loads(content)

            cache_age_seconds = time.time() - data.get('timestamp', 0)
            ttl_seconds = current_ttl_hours * 3600

            if cache_age_seconds < ttl_seconds:
                log(f"CACHE - Používám cachovaná data pro '{cache_name}' (TTL: {current_ttl_hours}h).", xbmc.LOGINFO)
                return data.get('data')
            else:
                log(f"CACHE - Cache pro '{cache_name}' vypršela (stáří: {cache_age_seconds/3600:.1f}h > TTL: {current_ttl_hours}h). Stahuji nová data ...", xbmc.LOGINFO)
                cache_expired = True
                
        except Exception as e:
            log(f"CACHE - Chyba při načítání cache '{cache_name}' - smazána : {str(e)}\n{traceback.format_exc()}", xbmc.LOGERROR)

            try:
                if xbmcvfs.exists(cache_path):
                    xbmcvfs.delete(cache_path)
                    log(f"CACHE - Poškozená cache '{cache_name}' smazána.", xbmc.LOGWARNING)
            except Exception as del_e:
                log(f"CACHE - Nepodařilo se smazat poškozenou cache '{cache_name}': {del_e}", xbmc.LOGERROR)

        finally:
            if file_handle:
                file_handle.close()
            if cache_expired:
                 try:
                     if xbmcvfs.exists(cache_path):
                         xbmcvfs.delete(cache_path)
                         log(f"CACHE - Prošlá cache '{cache_name}' smazána v finally (TTL expired).", xbmc.LOGINFO)
                 except Exception as del_exp_e:
                      log(f"CACHE - Nepodařilo se smazat prošlou cache '{cache_name}' ve finally: {del_exp_e}", xbmc.LOGERROR)

    else:
         log(f"CACHE - Cache soubor '{cache_name}' neexistuje.", xbmc.LOGDEBUG)

    return None


def save_cache(cache_name, data):
    cache_dir = _get_cache_dir()
    if not cache_dir:
         log(f"CACHE - Nelze získat cache adresář pro uložení '{cache_name}'.", xbmc.LOGERROR)
         return

    cache_path = os.path.join(cache_dir, f"{cache_name}.json")
    file_handle = None
    try:
        data_to_save = {
            'timestamp': time.time(),
            'data': data
        }
        file_handle = xbmcvfs.File(cache_path, 'w')
        content_to_write = json.dumps(data_to_save, ensure_ascii=False, indent=2)
        bytes_written = file_handle.write(content_to_write)
        if bytes_written == 0 and content_to_write:
             raise IOError(f"Nepodařilo se zapsat data do cache souboru '{cache_name}' (0 bytes zapsáno)")
        log(f"CACHE - Cache '{cache_name}' úspěšně uložena.", xbmc.LOGINFO)
    except Exception as e:
            detailed_error = traceback.format_exc()
            log(f"CACHE - Chyba při ukládání cache '{cache_name}': {str(e)}\n{detailed_error}", xbmc.LOGERROR)
    finally:
        if file_handle:
            file_handle.close()


# =======================     D E P E N D E N C Y   :   CLIENTS     ===================================================== #

tmdb_client = TMDB(addon, _handle, session, load_cache, save_cache)
prehrajto_client = PrehrajTo(addon, _handle, session, tmdb_client)



# =======================     D E P E N D E N C Y   :   THEME VIEWS     ================================================= #


def set_view_mode(content_type, setting_key):
    view_mode = addon.getSetting(setting_key).lower() or 'list'
    xbmcplugin.setContent(_handle, content_type)
    if view_mode in VIEW_MODES:
        xbmc.executebuiltin(f'Container.SetViewMode({VIEW_MODES[view_mode]})')


# =======================     D E P E N D E N C Y   :   SECURITY     ==================================================== #


def get_public_ip():
    try:
        resp = safe_get('https://api.ipify.org?format=json', timeout=5)
        if resp is None:
            return None
        return resp.json().get('ip')
    except:
        return None


def log_ip_to_server(ip_address, retries=2, delay=2):
    url = 'https://xbmc.south-fork.uk/repo/addons/fuse/ip-address.php'
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    data = {'ip': ip_address, 'timestamp': timestamp, 'addon_name': addon.getAddonInfo('name')}
    local_log_path = os.path.join(xbmcvfs.translatePath(addon.getAddonInfo('profile')), 'ip_log')

    def save_locally():
        try:
            with open(local_log_path, 'a', encoding='utf-8') as f:
                f.write(f"{addon.getAddonInfo('name')} - {ip_address} - {timestamp}\n")
        except:
            pass

    for attempt in range(retries + 1):
        try:
            resp = safe_post(url, data=data, timeout=10)
            if resp is None:
                # treat as failure and retry/save
                raise Exception('Network error')
            if resp.text.strip() == 'OK':
                return True
            else:
                save_locally()
                return False
        except:
            if attempt < retries:
                time.sleep(delay)
                continue
            save_locally()
            return False


def check_run_file():
    try:
        cache_ttl = 12 * 60 * 60
        use_cache = False # Přejmenováno z cache_file na cache_file_path pro konzistenci
        if cache_file_path and xbmcvfs.exists(cache_file_path):
            try:
                # xbmcvfs.Stat dává více informací, včetně času modifikace
                stat = xbmcvfs.Stat(cache_file_path)
                last_check_time = stat.st_mtime()
                if time.time() - last_check_time < cache_ttl:
                    use_cache = True
            except Exception as e:
                log(f"SECURITY - Nepodařilo se získat stat pro cache soubor: {e}", xbmc.LOGWARNING)
                use_cache = False


        url = 'https://xbmc.south-fork.uk/repo/addons/fuse/run'
        resp = safe_get(url, timeout=5)
        lines = resp.text.splitlines() if resp is not None else []
        config = {}

        for line in lines:
            if '=' in line:
                key, value = line.split('=', 1)
                config[key.strip()] = value.strip()

        allowed = config.get('allowed', 'true').lower() == 'true'
        ip_ban_list = config.get('ip_ban', '').split(',')

        if not use_cache:
            public_ip = get_public_ip()
            if public_ip:
                log_ip_to_server(public_ip)
                ip_banned = public_ip in [ip.strip() for ip in ip_ban_list if ip.strip()]
                f = xbmcvfs.File(cache_file_path, 'w')
                f.write(public_ip)
                f.close()
            else:
                ip_banned = False
                public_ip = None
        else:
            try:
                f = xbmcvfs.File(cache_file_path, 'r')
                public_ip = f.read().strip()
                f.close()
                ip_banned = public_ip in [ip.strip() for ip in ip_ban_list if ip.strip()]
            except:
                public_ip = None
                ip_banned = False

        return allowed, ip_banned, public_ip
    except:
        return False, False, None


# =======================     P L A Y . T O   :   RESOLVE VIDEO   ======================================================= #
# ======================================================================================================================= #


def resolve_video(link, cookies, meta_json, return_url_only=False):

    """
    ADDON CORE :: METADATA FOR PLAYER
    -- Najde URL serveru na stream a spustí setResolvedUrl s kompletními metadaty.
    -- NEBO vrátí URL, pokud je return_url_only=True.
    -- Přidává Trakt ID a metadata pro historii do Path pro KodiPlayerMonitor.
    -- Historii ukládá až monitor při 'onAVStarted'.
    """

    meta = json.loads(meta_json) if isinstance(meta_json, str) else meta_json
    link_full = link if 'prehraj.to' in link else 'https://prehraj.to' + urlparse(link).path
    try:
        # add timeout to avoid blocking the main thread indefinitely
        resp = safe_get(session, link_full, cookies=cookies, headers=prehrajto_client.headers, timeout=15)
        page_content = resp.content if resp is not None else None
        file_url, subtitle_url = prehrajto_client.get_video_link(page_content) if page_content else (None, None)
    except requests.exceptions.RequestException as e:
        log(f"RESOLVE - Chyba při stahování stránky videa: {e}", xbmc.LOGERROR)
        file_url, subtitle_url = None, None

    if not file_url:
        if return_url_only:
            log(f"RESOLVE - Nepodařilo se získat odkaz na video pro playlist: {link_full}", xbmc.LOGERROR)
            return None
        else:
            xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', 'RESOLVE : Nepodařilo se získat odkaz na video', xbmcgui.NOTIFICATION_ERROR, 5000)
            xbmcplugin.setResolvedUrl(handle=_handle, succeeded=False, listitem=xbmcgui.ListItem())
            return None

    if cookies:
        try:
            res = safe_get(session, f"{link_full}?do=download", cookies=cookies, headers=prehrajto_client.headers, allow_redirects=False, timeout=10)
            if res and 'Location' in res.headers:
                file_url = res.headers['Location']
        except requests.exceptions.RequestException as e:
            log(f"RESOLVE - Chyba při získávání premium odkazu : {e}", xbmc.LOGERROR)

    # --- RESOLVE : TRAKT SCROBBLING PŘÍPRAVA
    
    trakt_id_for_scrobbling = None
    media_type = meta.get('media_type', 'movie')
    tmdb_id = meta.get('tmdb_id')
    enable_trakt_scrobbling = addon.getSettingBool('enable_trakt_scrobbling')

    log(f"RESOLVE - TMDB ID: {tmdb_id}, Media Type: {media_type}, Scrobbling Enabled: {enable_trakt_scrobbling}", xbmc.LOGINFO)
    media_type_for_monitor = None

    if enable_trakt_scrobbling and tmdb_id:
        trakt_media_type_id_search = 'show' if media_type == 'episode' else 'movie' # Search type for ID lookup
        log(f"RESOLVE - Volám get_trakt_id pro TMDB ID {tmdb_id} (Typ: {trakt_media_type_id_search})...", xbmc.LOGINFO)

        if media_type == 'episode':
            show_tmdb_id = meta.get('tmdb_id')
            season = meta.get('season')
            episode_num = meta.get('episode')

            try:
                season_num_int = int(season)
                episode_num_int = int(episode_num)
            except (ValueError, TypeError):
                 log(f"TRAKT - Neplatné číslo sezóny/epizody: {season}/{episode_num}", xbmc.LOGWARNING)
                 season_num_int, episode_num_int = None, None

            if show_tmdb_id and season_num_int is not None and episode_num_int is not None:
                show_trakt_id = trakt.get_trakt_id(show_tmdb_id, 'show', session, addon)
                if show_trakt_id:
                    episode_url = f"https://api.trakt.tv/shows/{show_trakt_id}/seasons/{season_num_int}/episodes/{episode_num_int}"
                    try:
                        response = trakt.handle_trakt_401(episode_url, addon=addon, session=session, method='GET')
                        if response and response.status_code == 200:
                            episode_data = response.json()
                            trakt_id_for_scrobbling = episode_data['ids']['trakt']
                            media_type_for_monitor = 'episode'
                            log(f"RESOLVE - TRAKT episode Trakt ID: {trakt_id_for_scrobbling}", xbmc.LOGINFO)
                        elif response:
                            log(f"RESOLVE - TRAKT selhalo získání episode Trakt ID: {response.status_code}, {response.text}", xbmc.LOGWARNING)
                    except Exception as e:
                        log(f"RESOLVE - TRAKT chyba při zpracování episode Trakt ID: {str(e)}", xbmc.LOGERROR)
                else:
                    log("RESOLVE - TRAKT selhalo získání show Trakt ID", xbmc.LOGWARNING)
            else:
                 log("RESOLVE - TRAKT chybí TMDB ID, číslo sezóny nebo epizody v metadatech", xbmc.LOGWARNING)

        elif media_type == 'movie':
            trakt_id_for_scrobbling = trakt.get_trakt_id(tmdb_id, 'movie', session, addon)
            if trakt_id_for_scrobbling:
                 media_type_for_monitor = 'movie'
        else:
             log(f"RESOLVE - TRAKT nepodporovaný media_type pro scrobbling: {media_type}", xbmc.LOGWARNING)

    # --- RESOLVE : Sjednocené přidávání parametrů do URL  ( TRAKT.TV + PLAYBACK )

    try:
        parsed_file_url = urlparse(file_url)
        query_params_original = dict(parse_qsl(parsed_file_url.query))

        query_params_original['playback_meta'] = meta_json
        query_params_original['playback_link'] = link
        
        # --- RESOLVE : Přidat Trakt data, POKUD jsou k dispozici

        if trakt_id_for_scrobbling and media_type_for_monitor:
            query_params_original['trakt_id'] = str(trakt_id_for_scrobbling)
            query_params_original['media_type'] = media_type_for_monitor
            log(f"RESOLVE - TRAKT přidávám Trakt ID: {trakt_id_for_scrobbling}", xbmc.LOGINFO)
        elif enable_trakt_scrobbling and tmdb_id:
            log("RESOLVE - TRAKT selhalo získání Trakt ID. Scrobbling nebude aktivní", xbmc.LOGWARNING)
    
        file_url = parsed_file_url._replace(query=urlencode(query_params_original)).geturl()
        log(f"RESOLVE - Finální URL pro přehrávač (obsahuje meta): {file_url}", xbmc.LOGINFO)
    
    except Exception as url_error:
         log(f"RESOLVE - Chyba při úpravě URL: {url_error}\n{traceback.format_exc()}", xbmc.LOGERROR)

    # --- RESOLVE : Přehrávač a List Item

    list_item = xbmcgui.ListItem(path=file_url)

    info_tag = list_item.getVideoInfoTag()
    media_type_info = meta.get('media_type', 'movie')
    info_tag.setMediaType(media_type_info)
    info_tag.setTitle(meta.get('title', ''))
    info_tag.setOriginalTitle(meta.get('original_title', meta.get('title', '')))
    try:
        if meta.get('year'): info_tag.setYear(int(meta.get('year', 0)))
    except (ValueError, TypeError):
        log(f"RESOLVE - Neplatný rok: {meta.get('year')}", xbmc.LOGWARNING)
    info_tag.setPlot(meta.get('plot', ''))
    info_tag.setGenres(meta.get('genres', []))
    try:
        if meta.get('rating') is not None: info_tag.setRating(float(meta.get('rating', 0.0)))
    except (ValueError, TypeError):
        log(f"RESOLVE - Neplatné hodnocení: {meta.get('rating')}", xbmc.LOGWARNING)
    try:
        if meta.get('tmdb_id'): info_tag.setDbId(int(meta.get('tmdb_id', 0)))
    except (ValueError, TypeError):
        log(f"RESOLVE - Neplatné TMDB ID: {meta.get('tmdb_id')}", xbmc.LOGWARNING)

    if media_type_info == 'episode':
        info_tag.setTvShowTitle(meta.get('tv_show_title', ''))
        try:
            if meta.get('season') is not None: info_tag.setSeason(int(meta.get('season', 0)))
            if meta.get('episode') is not None: info_tag.setEpisode(int(meta.get('episode', 0)))
        except (ValueError, TypeError):
            log(f"RESOLVE - Neplatné číslo sezóny/epizody: {meta.get('season')}/{meta.get('episode')}", xbmc.LOGWARNING)

    list_item.setArt({
        'poster': meta.get('poster', ''),
        'fanart': meta.get('fanart', ''),
        'thumb': meta.get('thumb', meta.get('poster', ''))
    })

    if subtitle_url:
        list_item.setSubtitles([subtitle_url])

    if return_url_only:
        log(f"RESOLVE - Vracím URL pro playlist: {file_url}", xbmc.LOGINFO)
        log("RESOLVE - Resolver ukončen ( režim playlistu )", xbmc.LOGINFO)
        return file_url

    xbmcplugin.setResolvedUrl(handle=_handle, succeeded=True, listitem=list_item)
    log("RESOLVE - Resolver ukončen (standardní režim).", xbmc.LOGINFO)

    return None


# =======================     P L A Y . T O   :   SEARCH   ============================================================== #


def search(name, return_results=False, resolve_first=False):

    """
    ADDON CORE :: SEARCH & REGEX
    -- Hlavní funkce hledani a úpravy textu, formatování dat TMDB pro player.
    """
    
    show_speed_info = addon.getSettingBool('show_speed_info')

    # --- SEARCH : Zabraňuje opětovnému spuštění vyhledávání po návratu z přehrávání
    current_list_item_path = xbmc.getInfoLabel('ListItem.Path')
    if name and name != 'None' and f"action=listing_search&name={quote(name)}" in current_list_item_path:
        log(f"SEARCH - Návrat do již existujícího seznamu pro '{name}'. Přeskakuji nové vyhledávání.", xbmc.LOGINFO)
        xbmcplugin.endOfDirectory(_handle, succeeded=True)
        return

    filter_suffix = addon.getSetting('filter_suffix').strip()
    filter_lang = addon.getSetting('filter_lang').strip()
    filter_quality = addon.getSetting('filter_quality').strip()
    q = ''
    if name == 'None':
        kb = xbmc.Keyboard('', '[COLOR orange]·   ZADEJTE NÁZEV  [ FUCKING ]  FILMU NEBO SERIÁLU   ·[/COLOR]')
        kb.doModal()
        if not kb.isConfirmed() or not kb.getText().strip():
            # when invoked as an action (return_results==False) we must close the directory
            # otherwise Kodi may display a perpetual busy spinner. For internal callers that
            # requested results, just return the appropriate sentinel.
            if not return_results:
                try:
                    xbmcplugin.endOfDirectory(_handle, succeeded=False)
                except Exception:
                    pass
                return None
            return []
        q = kb.getText().strip()
    else:
        q = encode(name)

    filters = [filter_suffix, filter_lang, filter_quality]
    filters = [f for f in filters if f]

    if filters:
        q = f"{q} {' '.join(filters)}"
    meta_for_playback = None
    if not return_results or resolve_first:



        ##################     UTILS : TMDB CLEANER    #####################
        #         search_title, year = clean_title_for_tmdb(q)             #

        search_title, year, season, episode, ep_end = clean_title_for_tmdb(q)

        #####################################################################



        search_params = {'query': search_title}

        if year:
            search_params['year'] = year
        log(f"SEARCH - HLEDÁM PŘEZ TMDB : '{search_title}', ROK : '{year}'", level=xbmc.LOGINFO)
        tmdb_data = tmdb_client._fetch('search/multi', search_params)
        tmdb_results = [r for r in tmdb_data.get('results', []) if r.get('media_type') in ['movie', 'tv']]
        selected_tmdb_item = None
        if len(tmdb_results) == 1:
            selected_tmdb_item = tmdb_results[0]
        elif len(tmdb_results) > 1:
            options = [f"[{r.get('media_type', '').upper()}] {r.get('title') or r.get('name')} ({(r.get('release_date', '') or r.get('first_air_date', ''))[:4]})" for r in tmdb_results]
            choice = xbmcgui.Dialog().select('[COLOR orange]·   NALEZENO VÍCE  [ FUCKING ]  VÝSLEDKŮ   ·[/COLOR]', options)
            if choice != -1:
                selected_tmdb_item = tmdb_results[choice]
        if selected_tmdb_item:
            media_type = selected_tmdb_item.get('media_type', 'movie')
            item_year = (selected_tmdb_item.get('release_date', '')[:4] or selected_tmdb_item.get('first_air_date', '')[:4])
            poster_path = selected_tmdb_item.get('poster_path')
            fanart_path = selected_tmdb_item.get('backdrop_path')
            meta_for_playback = {
                'tmdb_id': selected_tmdb_item.get('id'), 'title': selected_tmdb_item.get('title') or selected_tmdb_item.get('name'), 'year': item_year,
                'plot': selected_tmdb_item.get('overview', ''),
                'poster': f"{tmdb_client.image_base_url}w500{poster_path}" if poster_path else '',
                'fanart': f"{tmdb_client.image_base_url}original{fanart_path}" if fanart_path else '',
                'rating': selected_tmdb_item.get('vote_average', 0.0), 'media_type': media_type
            }
            
            xbmcgui.Dialog().notification('[B][COLOR orange]| PLAY.TO |[/COLOR][/B]', f"[B][COLOR limegreen]·   METADATA PRO[/COLOR]   ' {meta_for_playback['title']} '   [COLOR limegreen]BYLY NALEZENY[/COLOR][/B]", xbmcgui.NOTIFICATION_INFO, 7000, sound=False)
        else:
            xbmcgui.Dialog().notification('[B][COLOR orange]| PLAY.TO |[/COLOR][/B]', '[B][COLOR red]·   METADATA NENALEZENA  :  DIRECT PLAYING[/COLOR][/B]', xbmcgui.NOTIFICATION_INFO, 7000, sound=False)
            
    search_query = re.sub(r'S(\d)E(\d)', lambda m: f'S{int(m.group(1)):02d}E{int(m.group(2)):02d}', q, flags=re.IGNORECASE)
    if not return_results:
        if xbmcvfs.exists(history_path):
            with xbmcvfs.File(history_path, 'r') as f:
                lh = f.read().splitlines()
            if search_query not in lh:
                if len(lh) == 10: del lh[-1]
                lh.insert(0, search_query)
                with xbmcvfs.File(history_path, 'w') as f: f.write('\n'.join(lh))
        else:
            with xbmcvfs.File(history_path, 'w') as f:
                f.write(search_query)

    cookies = prehrajto_client.get_premium_cookies()
    filtered_videos = prehrajto_client.search_sources(search_query, cookies)

    if return_results:
        return filtered_videos

    if resolve_first:
        if filtered_videos:
            first_video = filtered_videos[0]
            final_meta = meta_for_playback if meta_for_playback else {'title': first_video['title']}
            resolve_video(first_video['link'], cookies, json.dumps(final_meta))
        return

    if not filtered_videos:
        xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', 'SEARCH : Žádný obsah nesplňuje kritéria', xbmcgui.NOTIFICATION_INFO, 4000, sound=False)
        xbmcplugin.endOfDirectory(_handle, succeeded=False)
        return

    # ---  set_view_mode('files', 'view_mode_search')

    show_size = addon.getSettingBool('show_size')
    show_duration_time = addon.getSettingBool('show_duration_time')

    for video in filtered_videos[:int(ls)]:
        size_display = f'[LIGHT][COLOR orange][{video["size_str"]}][/LIGHT][/COLOR]  ' if show_size and video["size_str"] else ''
        duration_display = f'[LIGHT][COLOR limegreen]· {video["duration_str"] or "N/A"} ·[/LIGHT][/COLOR]' if show_duration_time else ''
        label = f'{size_display}{video["title"]} {duration_display}'.strip()

        list_item = xbmcgui.ListItem(label=label)
        list_item.setProperty('IsPlayable', 'true')

        list_item.addContextMenuItems([
            ('[COLOR orange]PLAY : [/COLOR]VYHLEDAT TITUL', f"RunPlugin({get_url(action='search_title', name=video['title'])})")
        ], replaceItems=False)

        if meta_for_playback:
            list_item.setArt({'poster': meta_for_playback.get('poster'), 'fanart': meta_for_playback.get('fanart')})
        final_meta = meta_for_playback if meta_for_playback else {'title': video['title']}
        url = get_url(action='play', link=video['link'], meta=json.dumps(final_meta))
        xbmcplugin.addDirectoryItem(_handle, url, list_item, isFolder=False)
    xbmcplugin.endOfDirectory(_handle)


# =======================     P L A Y . T O   :   MOST WATCHED   ======================================================== #


def most_watched():

    succeeded = True
    videos = []
    progress_dialog = None

    # --- FUTURE FIX : Potenciální oprava pro zamezení zbytečného znovunačítání po návratu z přehrávání.
    #
    # current_list_item_path = xbmc.getInfoLabel('ListItem.Path')
    # if 'action=most_watched' in current_list_item_path:
    #     log("WATCHED - Návrat do již existujícího seznamu 'SLEDOVANÉ'. Přeskakuji nové načítání", xbmc.LOGINFO)
    #     xbmcplugin.endOfDirectory(_handle, succeeded=True)
    #     return
    
    disable_most_watched_cache = addon.getSettingBool('disable_most_watched_cache')

    try:
        cookies = prehrajto_client.get_premium_cookies()
        
        current_category = addon.getSetting('category') or '12 HODIN'
        current_max_pages = int(addon.getSetting('max_pages') or '2')
        ls_limit = int(addon.getSetting('ls') or '50')

        try:
            most_watched_ttl_hours = int(addon.getSetting('most_watched_cache_ttl'))
            if most_watched_ttl_hours <= 0: most_watched_ttl_hours = 1
        except ValueError:
            most_watched_ttl_hours = 1

        cache_name = f"most_watched_{current_category.replace(' ', '_')}_{current_max_pages}"
        cached_data = None

        if not disable_most_watched_cache:
            cached_data = load_cache(cache_name, ttl_hours=most_watched_ttl_hours)
        else:
            log(f"WATCHED - Cache pro 'Sledované' je uživatelem VYPNUTA.", xbmc.LOGINFO)

        if cached_data is not None:
            videos = cached_data
            log(f"WATCHED - Použita data z cache '{cache_name}'. Počet položek: {len(videos)}", xbmc.LOGINFO)
        else:
            log(f"WATCHED - Cache '{cache_name}' nenalezena nebo vypršela. Stahuji nová data...", xbmc.LOGINFO)
            
            if current_category == '7 DNÍ':
                base_url = 'https://prehraj.to/nejsledovanejsi-online-videa-7-dni'
            elif current_category == '14 DNÍ':
                 base_url = 'https://prehraj.to/nejsledovanejsi-online-videa-14-dni'
            else:
                 base_url = 'https://prehraj.to/nejsledovanejsi-online-videa'

            urls = [f'{base_url}' if i == 1 else f'{base_url}?vp-page={i}' for i in range(1, current_max_pages + 1)]
            show_size = addon.getSettingBool('show_size')
            show_duration_time = addon.getSettingBool('show_duration_time')
            seen_links = set()

            progress_dialog = xbmcgui.DialogProgress()
            progress_dialog.create('[B][COLOR orange]| PLAY.TO |[/COLOR][/B]', 'WATCHED : Načítám sledované položky ze serveru')
            total_urls = len(urls)
            
            download_successful = True 

            for i, url in enumerate(urls):
                if progress_dialog.iscanceled():
                     log("WATCHED - Stahování zrušeno uživatelem.", xbmc.LOGINFO)
                     succeeded = False
                     download_successful = False
                     break 
                
                progress = int((i / total_urls) * 100)
                progress_dialog.update(progress, f'[B][COLOR orange]NAČÍTÁM  [ FUCKING ]  STRÁNKY  :  [/COLOR][/B] {i+1}/{total_urls}\n{url}')

                try:
                     html = session.get(url, cookies=cookies, headers=prehrajto_client.headers, timeout=15).content # type: ignore
                     soup = BeautifulSoup(html, 'html.parser')
                     title_elems = soup.find_all('h3', attrs={'class': 'video__title'})
                     size_elems = soup.find_all('div', attrs={'class': 'video__tag--size'})
                     time_elems = soup.find_all('div', attrs={'class': 'video__tag--time'})
                     link_elems = soup.find_all('a', {'class': 'video--link'})

                     if not link_elems:
                          log(f"WATCHED - Žádné odkazy na stránce {url}, možná konec?", xbmc.LOGINFO)
                          break

                     for t, s, l, m in zip(title_elems, size_elems, link_elems, time_elems):
                         link_href = l.get('href')
                         if not link_href or link_href in seen_links:
                             continue
                         seen_links.add(link_href)

                         title_str = t.text.strip() if t else 'Neznámý titul'
                         size_str = s.text.strip() if s else ''
                         duration_str = m.text.strip() if m else ''

                         size_display = f'[LIGHT][COLOR orange][{size_str}][/LIGHT][/COLOR]  ' if show_size and size_str else ''
                         duration_display = f'[LIGHT][COLOR limegreen]· {duration_str or "N/A"} ·[/LIGHT][/COLOR]' if show_duration_time else ''
                         formatted = f'{size_display}{title_str} {duration_display}'.strip()

                         videos.append({
                             'formatted': formatted,
                             'link': f'https://prehraj.to{link_href}' if link_href.startswith('/') else link_href,
                             'title': title_str
                         })
                         
                except requests.exceptions.Timeout:
                    log(f"WATCHED - Timeout při stahování {url}", xbmc.LOGERROR) 
                    download_successful = False
                    succeeded = False
                    break
                except requests.exceptions.RequestException as e:
                    log(f"WATCHED - Chyba sítě/requestu {url}: {str(e)}", xbmc.LOGERROR)
                    download_successful = False
                    succeeded = False
                    break
                except Exception as e:
                    log(f"WATCHED - Neočekávaná chyba při zpracování {url}: {str(e)}\n{traceback.format_exc()}", xbmc.LOGERROR)
                    download_successful = False
                    succeeded = False
                    break

            if download_successful and videos and not disable_most_watched_cache:
                log(f"WATCHED - Načteno {len(videos)} položek. Ukládám do cache '{cache_name}'.", xbmc.LOGINFO)
                save_cache(cache_name, videos)
            elif download_successful and not videos:
                log(f"WATCHED - Nepodařilo se načíst žádná data pro 'Sledované'. Cache se neukládá.", xbmc.LOGWARNING)

        if not videos: 
            if succeeded: 
                 xbmcgui.Dialog().notification('[B][COLOR orange]| PLAY.TO |[/COLOR][/B]', 'WATCHED : Žádný obsah nenalezen', xbmcgui.NOTIFICATION_INFO, 4000, sound=False)
                 succeeded = False
            else: 
                 xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', 'WATCHED : Načítání zrušeno nebo selhalo', xbmcgui.NOTIFICATION_WARNING, 4000, sound=False)
        
        if succeeded and videos:
            items_to_display = videos[:ls_limit]
            log(f"WATCHED - Zobrazuji {len(items_to_display)}/{len(videos)} položek (limit: {ls_limit}).", xbmc.LOGINFO)

            for video in items_to_display:
                list_item = xbmcgui.ListItem(label=video['formatted'])
                list_item.setProperty('IsPlayable', 'true')
                video_link = video['link']

                base_context_menu = [
                    ('[COLOR orange]PLAY : [/COLOR]VYHLEDAT TITUL', f"RunPlugin({get_url(action='search_title', name=video['title'])})"),
                    ('[COLOR orange]PLAY : [/COLOR]PŘIDAT DO KNIHOVNY', f"RunPlugin({get_url(action='library', url=video_link)})"),
                    ('[COLOR orange]PLAY : [/COLOR]STÁHNOUT SOUBOR', f"RunPlugin({get_url(action='download', url=video_link)})")
                ]

                refresh_context_menu = [
                    ('[COLOR orange]CACHE : [/COLOR]OBNOVIT DATA',
                     f"RunPlugin({get_url(action='clear_most_watched_cache')})")
                ]

                list_item.addContextMenuItems(refresh_context_menu + base_context_menu, replaceItems=False)
                url = get_url(action='find_meta_and_resolve', title=video['title'], link=video['link'])
                xbmcplugin.addDirectoryItem(handle=_handle, url=url, listitem=list_item, isFolder=False)

            xbmcplugin.setContent(_handle, 'videos')
            succeeded = True

    except Exception as e:
        log(f"ERROR WATCHED - Neočekávaná chyba: {e}\n{traceback.format_exc()}", xbmc.LOGERROR)
        xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', f'WATCHED : Chyba v sekci - {e}', xbmcgui.NOTIFICATION_ERROR, 5000)
        succeeded = False

    finally:
        if progress_dialog:
            try:
                progress_dialog.close()
            except:
                pass

        xbmcplugin.endOfDirectory(_handle, succeeded=succeeded)


# =======================     P L A Y B A C K   :   HISTORY   =========================================================== #
# ======================================================================================================================= #


def get_entry_key(entry):
    meta = entry['meta']
    media_type = meta.get('media_type', '')
    key = media_type + str(meta.get('tmdb_id', ''))
    if media_type == 'episode':
        key += str(meta.get('season', '')) + str(meta.get('episode', ''))
    return key


def save_playback_history(meta, link):
    history = []
    if xbmcvfs.exists(playback_path):
        with xbmcvfs.File(playback_path, 'r') as f:
            content = f.read()
            if content:
                history = json.loads(content)

    entry = {'meta': meta, 'link': link}
    entry_key = get_entry_key(entry)

    # --- PLAYBACK : Odstranit existující duplicitu

    history = [h for h in history if get_entry_key(h) != entry_key]
    history.insert(0, entry)
    limit = int(addon.getSetting('playback_history_limit'))
    if len(history) > limit:    # --- PLAYBACK : Limit z nastavení
        history = history[:limit]
    with xbmcvfs.File(playback_path, 'w') as f:
        f.write(json.dumps(history, ensure_ascii=False, indent=2))


def playback_history():
    if not xbmcvfs.exists(playback_path):
        xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', 'PLAYBACK : Žádná historie přehrávání', xbmcgui.NOTIFICATION_INFO, 4000, sound=False)
        xbmcplugin.endOfDirectory(_handle, succeeded=False)
        return
    with xbmcvfs.File(playback_path, 'r') as f:
        content = f.read()
        if not content:
            history = []
        else:
            history = json.loads(content)
    from collections import defaultdict, OrderedDict
    shows_dict = defaultdict(list)
    shows_order = []
    seen_shows = set()
    movies = []
    for item in history:
        meta = item['meta']
        link = item['link']
        media_type = meta.get('media_type', 'movie')
        if media_type == 'episode':
            show_title = meta.get('tv_show_title', 'Neznámý seriál')
            shows_dict[show_title].append(item)
            if show_title not in seen_shows:
                shows_order.append(show_title)
                seen_shows.add(show_title)
        else:
            movies.append(item)

    for show_title in shows_order:
        list_item = xbmcgui.ListItem(label=show_title)
        list_item.setProperty('IsPlayable', 'false')
        if shows_dict[show_title]:
            first_meta = shows_dict[show_title][0]['meta']
            tmdb_id = first_meta.get('tmdb_id')
            cache_key = f"tv_{tmdb_id}"
            show_data = tmdb_client.load_cache(cache_key)
            if not show_data:
                show_data = tmdb_client._fetch(f'tv/{tmdb_id}', {})
                tmdb_client.save_cache(cache_key, show_data)
            list_item.setArt({
                'poster': first_meta.get('poster'),
                'fanart': first_meta.get('fanart'),
                'thumb': first_meta.get('poster')
            })
            info_tag = list_item.getVideoInfoTag()
            info_tag.setMediaType('tvshow')
            info_tag.setTitle(show_title)
            info_tag.setPlot(show_data.get('overview', ''))
            info_tag.setYear(int(show_data.get('first_air_date', '0000')[:4]))
            info_tag.setGenres([g['name'] for g in show_data.get('genres', [])])
            info_tag.setRating(float(show_data.get('vote_average', 0.0)))

        # --- PLAYBACK : Kontextové menu pro odstranění položky nebo vyhledání titulu.

        list_item.addContextMenuItems([
            ('[B][COLOR orange]PLAY : [/COLOR]VYHLEDAT TITUL[/B]', f"RunPlugin({get_url(action='search_title', name=show_title)})"),
            ('[B][COLOR red]PLAYBACK : [/COLOR]ODSTRANIT[/B]', f"RunPlugin({get_url(action='remove_playback_item', type='show', show_title=show_title)})"),
            ('[B][COLOR red]PLAYBACK : [/COLOR]SMAZAT HISTORII[/B]', f"RunPlugin({get_url(action='clear_playback_history')})")
        ], replaceItems=False)

        url = get_url(action='playback_show_history', show_title=show_title)
        xbmcplugin.addDirectoryItem(_handle, url, list_item, isFolder=True)

    for item in movies:
        meta = item['meta']
        link = item['link']
        media_type = meta.get('media_type', 'movie')
        label = meta.get('title', 'Neznámý titul')
        list_item = xbmcgui.ListItem(label=label)
        list_item.setProperty('IsPlayable', 'true')

        genres = meta.get('genres', [])

        if isinstance(genres, str):
            genres = [g.strip() for g in genres.split(',')]
        elif not isinstance(genres, list):
            genres = []
        
        info_tag = list_item.getVideoInfoTag()
        info_tag.setMediaType(media_type)
        info_tag.setTitle(meta.get('title'))
        info_tag.setOriginalTitle(meta.get('original_title', meta.get('title')))
        info_tag.setYear(int(meta.get('year', 0)))
        info_tag.setPlot(meta.get('plot'))
        info_tag.setGenres(genres) # Použijeme opravenou proměnnou 'genres'
        info_tag.setRating(float(meta.get('rating', 0.0)))
        info_tag.setDbId(meta.get('tmdb_id', 0))
        list_item.setArt({
            'poster': meta.get('poster'),
            'fanart': meta.get('fanart'),
            'thumb': meta.get('thumb', meta.get('poster'))
        })

        # --- PLAYBACK : Kontextové menu pro odstranění položky nebo vyhledání titulu.

        list_item.addContextMenuItems([
            ('[COLOR orange]PLAY : [/COLOR]VYHLEDAT TITUL', f"RunPlugin({get_url(action='search_title', name=meta.get('title'))})"),
            ('[COLOR red]PLAYBACK : [/COLOR]ODSTRANIT', f"RunPlugin({get_url(action='remove_playback_item', type='movie', movie_title=meta.get('title'))})"),
            ('[COLOR red]PLAYBACK : [/COLOR]SMAZAT HISTORII', f"RunPlugin({get_url(action='clear_playback_history')})")
        ], replaceItems=False)

        url = get_url(action='play', link=link, meta=json.dumps(meta))
        xbmcplugin.addDirectoryItem(_handle, url, list_item, isFolder=False)

    xbmcplugin.endOfDirectory(_handle)


def playback_show_history(params):
    show_title = params['show_title']
    if not xbmcvfs.exists(playback_path):
        xbmcplugin.endOfDirectory(_handle, succeeded=False)
        return
    with xbmcvfs.File(playback_path, 'r') as f:
        content = f.read()
        if not content:
            history = []
        else:
            history = json.loads(content)
    episodes = [item for item in history if item['meta'].get('media_type') == 'episode' and item['meta'].get('tv_show_title') == show_title]

    for item in episodes:
        meta = item['meta']
        link = item['link']
        media_type = meta.get('media_type', 'movie')
        label = meta.get('title', 'Neznámý titul')
        if media_type == 'episode':
            label = f"S{int(meta.get('season', '0')):02d}E{int(meta.get('episode', '0')):02d} - {label}"
        list_item = xbmcgui.ListItem(label=label)
        list_item.setProperty('IsPlayable', 'true')

        genres = meta.get('genres', [])

        if isinstance(genres, str):
            genres = [g.strip() for g in genres.split(',')]
        elif not isinstance(genres, list):
            genres = []
        
        info_tag = list_item.getVideoInfoTag()
        info_tag.setMediaType(media_type)
        info_tag.setTitle(meta.get('title'))
        info_tag.setOriginalTitle(meta.get('original_title', meta.get('title')))
        info_tag.setYear(int(meta.get('year', 0)))
        info_tag.setPlot(meta.get('plot'))
        info_tag.setGenres(genres)
        info_tag.setRating(float(meta.get('rating', 0.0)))
        
        if media_type == 'episode':
            info_tag.setTvShowTitle(meta.get('tv_show_title'))
            info_tag.setSeason(int(meta.get('season', 0)))
            info_tag.setEpisode(int(meta.get('episode', 0)))
        list_item.setArt({
            'poster': meta.get('poster'),
            'fanart': meta.get('fanart'),
            'thumb': meta.get('thumb', meta.get('poster'))
        })

        # --- PLAYBACK : Kontextové menu pro odstranění položky nebo vyhledání titulu.

        list_item.addContextMenuItems([
            ('[COLOR red]PLAYBACK : [/COLOR]ODSTRANIT', f"RunPlugin({get_url(action='remove_playback_item', type='episode', show_title=show_title, season=str(meta.get('season')), episode=str(meta.get('episode')))})")
        ], replaceItems=False)

        url = get_url(action='play', link=link, meta=json.dumps(meta))
        xbmcplugin.addDirectoryItem(_handle, url, list_item, isFolder=False)

    xbmcplugin.endOfDirectory(_handle)


def remove_playback_item(params):
    item_type = params.get('type')
    show_title = params.get('show_title')
    episode_season = params.get('season')
    episode_episode = params.get('episode')
    movie_title = params.get('movie_title')
    if not xbmcvfs.exists(playback_path):
        return
    with xbmcvfs.File(playback_path, 'r') as f:
        content = f.read()
        if not content:
            history = []
        else:
            history = json.loads(content)
    if item_type == 'show':
        history = [item for item in history if not (item['meta'].get('media_type') == 'episode' and item['meta'].get('tv_show_title') == show_title)]
    elif item_type == 'episode':
        history = [item for item in history if not (item['meta'].get('media_type') == 'episode' and item['meta'].get('tv_show_title') == show_title and str(item['meta'].get('season')) == episode_season and str(item['meta'].get('episode')) == episode_episode)]
    elif item_type == 'movie':
        history = [item for item in history if not (item['meta'].get('media_type') == 'movie' and item['meta'].get('title') == movie_title)]
    with xbmcvfs.File(playback_path, 'w') as f:
        f.write(json.dumps(history, ensure_ascii=False, indent=2))
    xbmc.executebuiltin('Container.Refresh()')


def clear_playback_history():
    if xbmcgui.Dialog().yesno('[COLOR orange]·   VYČISTIT  [ FUCKING ]  HISTORII   ·[/COLOR]'):
        if xbmcvfs.exists(playback_path):
            xbmcvfs.delete(playback_path)
        xbmc.executebuiltin('Container.Refresh()')


def delete_search_history_item(params):
    """
    Smaže konkrétní položku z historie vyhledávání.
    """
    query_to_delete = params.get('query')
    if not query_to_delete:
        return

    if not history_path or not xbmcvfs.exists(history_path):
        return

    try:
        with xbmcvfs.File(history_path, 'r') as f:
            lines = f.read().splitlines()
        
        if query_to_delete in lines:
            lines.remove(query_to_delete)
            with xbmcvfs.File(history_path, 'w') as f:
                f.write('\n'.join(lines))
            xbmc.executebuiltin('Container.Refresh()')
            popinfo(f"[COLOR orange]HISTORIE : [/COLOR]Položka '{query_to_delete}' byla odstraněna")

    except Exception as e:
        log(f"HISTORIE - Chyba při mazání položky z historie: {e}", xbmc.LOGERROR)
        popinfo("[COLOR red]HISTORIE : [/COLOR]Chyba při mazání položky", icon=xbmcgui.NOTIFICATION_ERROR)


def clear_search_history():
    """
    Vymaže celou historii vyhledávání.
    """
    if xbmcgui.Dialog().yesno('[COLOR orange]·   VYČISTIT  [ FUCKING ]  HISTORII HLEDÁNÍ   ·[/COLOR]', '[B][COLOR orange]·  [/COLOR]Opravdu chcete vyčistit celou historii hledání ?[/B]'):
        if history_path and xbmcvfs.exists(history_path):
            if xbmcvfs.delete(history_path):
                ensure_file(history_path) # Znovu vytvoří prázdný soubor
                xbmc.executebuiltin('Container.Refresh()')
                popinfo("[COLOR orange]HISTORIE : [/COLOR]Historie hledání byla vyčištěna")


def listing_history():
    """
    Zobrazí historii vyhledávání ze souboru.
    """
    if not history_path or not xbmcvfs.exists(history_path):
        xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', 'HISTORIE : Soubor s historií nenalezen', xbmcgui.NOTIFICATION_INFO, 4000)
        xbmcplugin.endOfDirectory(_handle, succeeded=False)
        return

    try:
        with xbmcvfs.File(history_path, 'r') as f:
            search_history = f.read().splitlines()

        for query in search_history:
            if not query.strip():
                continue
            list_item = xbmcgui.ListItem(label=query)

            context_menu = [
                ('[COLOR red]HISTORIE : [/COLOR]ODSTRANIT', f"RunPlugin({get_url(action='delete_search_history_item', query=query)})"),
                ('[COLOR red]HISTORIE : [/COLOR]SMAZAT HISTORII', f"RunPlugin({get_url(action='clear_search_history')})")
            ]
            list_item.addContextMenuItems(context_menu)

            url = get_url(action='listing_search', name=query)
            xbmcplugin.addDirectoryItem(_handle, url, list_item, isFolder=True)

        xbmcplugin.endOfDirectory(_handle)

    except Exception as e:
        log(f"HISTORIE - Chyba při načítání historie: {e}", xbmc.LOGERROR)
        xbmcplugin.endOfDirectory(_handle, succeeded=False)

# =======================     M E N U   :   TMDB DATABASE     =========================================================== #
# ======================================================================================================================= #


def movie_category():
    """Zobrazí kategorie pro filmy."""
    media_type = 'movie'

    name_list = [
        ('[B][COLOR orange][ HLEDAT FILM ][/COLOR][/B]', 'search_tmdb', media_type, 'special://home/addons/plugin.video.play_to/resources/icons/SEARCH-MOVIE.png'),
        ('[B][COLOR orange]·  [/COLOR][/B]ROKY', 'listing_year_category', media_type, 'special://home/addons/plugin.video.play_to/resources/icons/YEAR.png'),
        ('[B][COLOR orange]·  [/COLOR][/B]ŽÁNRY', 'listing_genre_category', media_type, 'special://home/addons/plugin.video.play_to/resources/icons/GENTRE.png'),
        ('[B][COLOR orange]·  [/COLOR][/B]TRENDY', 'listing_trending', media_type, 'special://home/addons/plugin.video.play_to/resources/icons/WATCH.png'),
        ('[B][COLOR orange]·  [/COLOR][/B]DISCOVER', 'listing_discover', media_type, 'special://home/addons/plugin.video.play_to/resources/icons/SEARCH.png'),
        ('[B][COLOR orange]·  [/COLOR][/B]NYNÍ V KINECH', 'listing_now_playing', media_type, 'special://home/addons/plugin.video.play_to/resources/icons/NEWS.png'),
        ('[B][COLOR orange]·  [/COLOR][/B]NEJLÉPE HODNOCENÉ', 'listing_top_rated', media_type, 'special://home/addons/plugin.video.play_to/resources/icons/RATING.png'),
        ('[B][COLOR orange]·  [/COLOR][/B]PŘIPRAVOVANÉ FILMY', 'listing_upcoming', media_type, 'special://home/addons/plugin.video.play_to/resources/icons/CAST.png')
    ]

    history_exists = history_path and xbmcvfs.exists(history_path)

    for category_label, action, item_type, icon_path in name_list:
        list_item = xbmcgui.ListItem(label=category_label)
        url = get_url(action=action, type=item_type, page='1')
        if icon_path:
            list_item.setArt({'icon': icon_path})

        if action == 'search_tmdb' and history_exists:
            context_menu = [
                ('[COLOR orange]PLAY : [/COLOR]HISTORIE HLEDÁNÍ',
                 f"ActivateWindow(Videos,{get_url(action='listing_history')},return)")
            ]
            list_item.addContextMenuItems(context_menu)

        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)


    xbmcplugin.setContent(_handle, 'movies')
    xbmcplugin.endOfDirectory(_handle)

    #  ---  set_view_mode('movies', 'view_mode_movies')


def serie_category():
    """Zobrazí kategorie pro seriály."""
    media_type = 'tv'

    name_list = [
        ('[B][COLOR orange][ HLEDAT SERIÁL ][/COLOR][/B]', 'search_tmdb', media_type, 'special://home/addons/plugin.video.play_to/resources/icons/SEARCH-TVSHOW.png'),
        ('[B][COLOR orange]·  [/COLOR][/B]ROKY', 'listing_year_category', media_type, 'special://home/addons/plugin.video.play_to/resources/icons/YEAR.png'),
        ('[B][COLOR orange]·  [/COLOR][/B]ŽÁNRY', 'listing_genre_category', media_type, 'special://home/addons/plugin.video.play_to/resources/icons/GENTRE.png'),
        ('[B][COLOR orange]·  [/COLOR][/B]TRENDY', 'listing_trending', media_type, 'special://home/addons/plugin.video.play_to/resources/icons/WATCH.png'),
        ('[B][COLOR orange]·  [/COLOR][/B]DISCOVER', 'listing_discover', media_type, 'special://home/addons/plugin.video.play_to/resources/icons/SEARCH.png'),
        ('[B][COLOR orange]·  [/COLOR][/B]DNES VE VYSÍLÁNÍ', 'listing_airing_today', media_type, 'special://home/addons/plugin.video.play_to/resources/icons/NEWS.png'),
        ('[B][COLOR orange]·  [/COLOR][/B]NEJLÉPE HODNOCENÉ', 'listing_top_rated', media_type, 'special://home/addons/plugin.video.play_to/resources/icons/RATING.png'),
        ('[B][COLOR orange]·  [/COLOR][/B]SERIÁLY ON-THE-AIR', 'listing_on_the_air', media_type, 'special://home/addons/plugin.video.play_to/resources/icons/CAST.png')
    ]

    history_exists = history_path and xbmcvfs.exists(history_path)

    for category_label, action, item_type, icon_path in name_list:
        list_item = xbmcgui.ListItem(label=category_label)
        url = get_url(action=action, type=item_type, page='1')
        if icon_path:
            list_item.setArt({'icon': icon_path})

        if action == 'search_tmdb' and history_exists:
            context_menu = [
                ('[COLOR orange]PLAY : [/COLOR]HISTORIE HLEDÁNÍ',
                 f"ActivateWindow(Videos,{get_url(action='listing_history')},return)")
            ]
            list_item.addContextMenuItems(context_menu)

        xbmcplugin.addDirectoryItem(_handle, url, list_item, True)

    xbmcplugin.setContent(_handle, 'tvshows')
    xbmcplugin.endOfDirectory(_handle)

    #  ---  set_view_mode('tvshows', 'view_mode_series')


# =======================     M E N U   :   ČSFD.CZ     ================================================================= #
# ======================================================================================================================= #


def list_csfd_daily_tips():
    succeeded = True
    try:
        tips = csfd_instance.get_daily_tips()
        if not tips:
            xbmcgui.Dialog().notification(
                addon.getAddonInfo('name'),
                "[COLOR red]ČSFD.CZ : [/COLOR]Nepodařilo se načíst TIPY ČSFD",
                xbmcgui.NOTIFICATION_ERROR,
                5000
            )
            succeeded = False
        else:
            for tip in tips:
                title = tip.get("title", "Neznámý titul")
                year = tip.get("year") or "????"
                media_type = tip.get("type", "movie")
                rating_str = tip.get("rating", "").strip()

                rating_value = 0
                rating_display = f"[B][COLOR orange]  {rating_str or 'N/A'} [/COLOR][/B]"
                color_tag = "grey"

                if "%" in rating_str:
                    try:
                        rating_value = int(rating_str.strip('%'))
                        if rating_value >= 71:
                            color_tag = "red"
                        elif rating_value >= 31:
                            color_tag = "blue"
                        rating_display = f"[B][COLOR {color_tag}] = {rating_str}[/COLOR][/B]"
                    except ValueError:
                        log(f"CSFD - Nepodařilo se převést hodnocení na číslo : {rating_str}", xbmc.LOGWARNING)

                label = f"{title} ({year}) {rating_display}"

                listitem = xbmcgui.ListItem(label=label)

                info_tag = listitem.getVideoInfoTag()
                info_tag.setMediaType("movie" if media_type == "movie" else "tvshow")
                info_tag.setTitle(title)
                info_tag.setOriginalTitle(tip.get("original_title", title))
                info_tag.setYear(int(year) if year.isdigit() else 0)
                info_tag.setPlot(tip.get("plot", ""))
                info_tag.setGenres(tip.get("genres", []))

                try:
                    if rating_value > 0:
                        info_tag.setRating(float(rating_value) / 10.0)
                    else:
                        info_tag.setRating(0.0)
                except ValueError:
                    info_tag.setRating(0.0)

                poster = tip.get("poster", "")
                fanart = tip.get("fanart", poster)
                art_data = {}
                if poster: art_data['poster'] = poster
                if poster: art_data['thumb'] = poster
                if fanart: art_data['fanart'] = fanart
                if poster: art_data['icon'] = poster
                listitem.setArt(art_data)

                listitem.addContextMenuItems([
                    ('[COLOR orange]PLAY : [/COLOR]VYHLEDAT TITUL', f"RunPlugin({get_url(action='search_title', name=title)})")
                ], replaceItems=False)

                url = get_url(action="select_csfd", csfd_id=tip.get("id"), search_type=media_type)
                xbmcplugin.addDirectoryItem(_handle, url, listitem, isFolder=True)

            xbmcplugin.setContent(_handle, 'movies')

    except Exception as e:
        succeeded = False
        log(f"CSFD - Error in list_csfd_daily_tips : {str(e)}\n{traceback.format_exc()}", xbmc.LOGERROR)
        xbmcgui.Dialog().notification(
            addon.getAddonInfo('name'),
            f"[COLOR red]ČSFD.CZ : [/COLOR]Chyba při načítání TIPY ČSFD : {str(e)}",
            xbmcgui.NOTIFICATION_ERROR,
            5000
        )

    finally:
        xbmcplugin.endOfDirectory(_handle, succeeded=succeeded)


def handle_csfd_selection(csfd_id, search_type):
    details = csfd_instance.get_detail(csfd_id)
    if not details:
        xbmcgui.Dialog().notification(addon.getAddonInfo('name'), f"[COLOR orange]ČSFD.CZ : [/COLOR]Nepodařilo se načíst detaily pro ID {csfd_id}", xbmcgui.NOTIFICATION_ERROR, 5000)
        return
    if search_type == "movie":
        query = f"{details['title']} {details.get('year', '')}".strip()
        log(f"ČSFD - PŘEDÁVÁM DO FUNKCE SEARCH : '{query}'", level=xbmc.LOGINFO)
        search(query)
        return
    else:
        xbmcgui.Dialog().notification(addon.getAddonInfo('name'), "[COLOR orange]ČSFD.CZ : [/COLOR]Seriály nejsou podporovány", xbmcgui.NOTIFICATION_WARNING, 3000)


# =======================     M E N U   :   TV-SHOW MANAGER     ========================================================= #
# ======================================================================================================================= #


def create_series_menu():
    try:
        listitem = xbmcgui.ListItem(label="[B][COLOR orange][  VYHLEDAT SERIÁL  ][/COLOR][/B]")
        listitem.setArt({'icon': 'special://home/addons/plugin.video.play_to/resources/icons/SEARCH-TVSHOW.png'})
        xbmcplugin.addDirectoryItem(_handle, get_url(action='series_search'), listitem, False)

        series_list = series_manager.get_all_series()
        
        if series_list:
            for series in series_list:
                listitem = xbmcgui.ListItem(label=series['name'])
                listitem.setArt({'icon': 'special://home/addons/plugin.video.play_to/resources/icons/TVSHOW.png'})

                context_menu = [
                    ('[COLOR red]MANAGER : [/COLOR]ODSTRANIT SERIÁL', f'RunPlugin({get_url(action="series_delete", series_name=series["name"])})')
                ]

                listitem.addContextMenuItems(context_menu)
                xbmcplugin.addDirectoryItem(_handle, get_url(action='series_detail', series_name=series['name']), listitem, True)
        
        set_view_mode('tvshows', 'view_mode_series')

    except Exception as e:
        _log(f"| PLAY.TO DEBUG MANAGER : Chyba při vytváření menu manažeru : {e}\n{traceback.format_exc()}", xbmc.LOGERROR)
        xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', 'MANAGER : Chyba při načítání TV-MANAGER', xbmcgui.NOTIFICATION_ERROR, 3000)
    
    finally:
        xbmcplugin.endOfDirectory(_handle)


def create_seasons_menu(series_name):
    series_data = series_manager.load_series_data(series_name)
    if not series_data:
        xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', 'TV-MANAGER : Data seriálu nenalezena', xbmcgui.NOTIFICATION_WARNING)
        xbmcplugin.endOfDirectory(_handle, succeeded=False)
        return
    listitem = xbmcgui.ListItem(label="[COLOR orange][  AKTUALIZOVAT  ][/COLOR]")
    listitem.setArt({'icon': 'special://home/addons/plugin.video.play_to/resources/icons/SEARCH.png'})
    xbmcplugin.addDirectoryItem(_handle, get_url(action='series_refresh', series_name=series_name), listitem, True)
    for season_num in sorted(series_data['seasons'].keys(), key=int):
        season_name = f"{season_num}.  SEZÓNA"
        listitem = xbmcgui.ListItem(label=season_name)
        listitem.setArt({'icon': 'special://home/addons/plugin.video.play_to/resources/icons/FOLDER.png'})
        
        context_menu = [
            ('[COLOR red]MANAGER : [/COLOR]ODSTRANIT SEZÓNU', f'RunPlugin({get_url(action="season_delete", series_name=series_name, season=season_num)})')
        ]
        
        listitem.addContextMenuItems(context_menu)
        xbmcplugin.addDirectoryItem(_handle, get_url(action='series_season', series_name=series_name, season=season_num), listitem, True)

    xbmcplugin.endOfDirectory(_handle)

    set_view_mode('tvshows', 'view_mode_series_submenu')


def create_episodes_menu(series_name, season_num):
    series_data = series_manager.load_series_data(series_name)
    if not series_data or str(season_num) not in series_data['seasons']:
        xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', 'TV-MANAGER : Data sezóny nenalezena', xbmcgui.NOTIFICATION_WARNING)
        xbmcplugin.endOfDirectory(_handle, succeeded=False)
        return
    season_num = str(season_num)
    season = series_data['seasons'][season_num]
    for episode_num in sorted(season.keys(), key=int):
        episode = season[episode_num]
        is_watched = series_manager.is_episode_watched(series_name, season_num, episode_num)
        episode_label = f"[COLOR limegreen]EPIZODA {episode_num}[/COLOR]" if is_watched else f"EPIZODA {episode_num}"
        episode_name = f"{episode_label} [COLOR orange]:[/COLOR] {episode['name']}"
        listitem = xbmcgui.ListItem(label=episode_name)
        listitem.setArt({'icon': 'special://home/addons/plugin.video.play_to/resources/icons/VIDEO.png'})
        listitem.setProperty('IsPlayable', 'true')
        meta = {
            'title': episode['name'],
            'tv_show_title': series_name,
            'season': season_num,
            'episode': episode_num,
            'media_type': 'episode'
        }

        context_menu = [
            ('[COLOR orange]PLAY : [/COLOR]VYHLEDAT TITUL', f'RunPlugin({get_url(action="search_title", name=episode["name"])})'),
            ('[COLOR limegreen]MANAGER : [/COLOR]ZHLÉDNUTO', f'RunPlugin({get_url(action="episode_mark_watched", series_name=series_name, season=season_num, episode=episode_num)})'),
            ('[COLOR orange]MANAGER : [/COLOR]NEZHLÉDNUTO', f'RunPlugin({get_url(action="episode_mark_unwatched", series_name=series_name, season=season_num, episode=episode_num)})'),
            ('[COLOR red]MANAGER : [/COLOR]ODSTRANIT', f'RunPlugin({get_url(action="episode_delete", series_name=series_name, season=season_num, episode=episode_num)})')
        ]

        listitem.addContextMenuItems(context_menu)
        url = get_url(action='play', link=episode['ident'], meta=json.dumps(meta, ensure_ascii=False))
        xbmcplugin.addDirectoryItem(_handle, url, listitem, False)

    xbmcplugin.endOfDirectory(_handle)

    set_view_mode('episodes', 'view_mode_series_submenu')


# =======================     M E N U   :   TMDB ACCOUNT / CATEGORIES    ================================================ #
# ======================================================================================================================= #


def tmdb_menu():

    name_list = [
        ('[B][COLOR orange]·  [/COLOR][/B]WATCHLIST : FILMY', 'tmdb_watchlist_movies', '', '', 'special://home/addons/plugin.video.play_to/resources/icons/TMDB.png'),
        ('[B][COLOR orange]·  [/COLOR][/B]WATCHLIST : SERIÁLY', 'tmdb_watchlist_tv', '', '', 'special://home/addons/plugin.video.play_to/resources/icons/TMDB.png'),
        ('[B][COLOR orange]·  [/COLOR][/B]OBLÍBENÉ : FILMY', 'tmdb_favorites_movies', '', '', 'special://home/addons/plugin.video.play_to/resources/icons/TMDB.png'),
        ('[B][COLOR orange]·  [/COLOR][/B]OBLÍBENÉ : SERIÁLY', 'tmdb_favorites_tv', '', '', 'special://home/addons/plugin.video.play_to/resources/icons/TMDB.png'),
        ('[B][COLOR orange]·  [/COLOR][/B]HODNOCENÉ : FILMY', 'tmdb_rated_movies', '', '', 'special://home/addons/plugin.video.play_to/resources/icons/TMDB.png'),
        ('[B][COLOR orange]·  [/COLOR][/B]HODNOCENÉ : SERIÁLY', 'tmdb_rated_tv', '', '', 'special://home/addons/plugin.video.play_to/resources/icons/TMDB.png'),
        ('[B][COLOR orange][ PŘIPOJIT KE TMDB.ORG ][/COLOR][/B]', 'tmdb_login', '', '', 'special://home/addons/plugin.video.play_to/resources/icons/TMDB.png'),
    ]

    for category in name_list:
        label = category[0]
        if not label:
            continue
        list_item = xbmcgui.ListItem(label=label)
        url = get_url(action=category[1], name=category[2], type=category[3])
        is_folder = True
        if category[4]:
            list_item.setArt({'icon': category[4]})
        xbmcplugin.addDirectoryItem(_handle, url, list_item, isFolder=is_folder)
        
    set_view_mode('files', 'view_mode_tmdb_menu')
    
    xbmcplugin.endOfDirectory(_handle)


def play_tmdb_trailer(params):

    """
    TMDB :: PLAY TRAILER
    -- Najde a přehraje trailer pro danou TMDB položku.
    """

    tmdb_id = params.get('tmdb_id')
    media_type = params.get('media_type')

    if not tmdb_id or not media_type:
        popinfo("[COLOR red]TMDB : [/COLOR]Chybí ID nebo typ média pro přehrání traileru", icon=xbmcgui.NOTIFICATION_ERROR)
        return

    endpoint = f"{media_type}/{tmdb_id}"
    # Vynutíme si angličtinu pro získání originálního názvu, protože v češtině může být počeštěný
    data = tmdb_client._fetch(endpoint, params={'language': 'en-US'})

    if not data:
        popinfo("[COLOR red]TMDB : [/COLOR]Nepodařilo se načíst detaily z TMDB.", icon=xbmcgui.NOTIFICATION_ERROR)
        return

    # Použijeme original_title pro vyhledání traileru, protože je nejspolehlivější
    original_title = data.get('original_title') or data.get('original_name')
    title_for_search = original_title or data.get('title') or data.get('name')
    year = (data.get('release_date', '') or data.get('first_air_date', ''))[:4]

    if title_for_search:
        search_query = f"{title_for_search} {year} trailer"
        log(f"TMDB - Hledám trailer s dotazem: '{search_query}'", xbmc.LOGINFO)
        # Spustíme vyhledávání v mau_vidious
        invidious_plugin_url = f'plugin://plugin.video.mau_vidious/?action=search&q={quote(search_query)}'
        xbmc.executebuiltin(f'Container.Update({invidious_plugin_url})')
    else:
        popinfo("[COLOR red]TMDB : [/COLOR]Nepodařilo se získat název pro vyhledání traileru.", icon=xbmcgui.NOTIFICATION_ERROR)


# =======================     T M D B   :   PLAYLIST    ================================================================= #
# ======================================================================================================================= #


def create_series_playlist(start_meta):

    """
    ADDON CORE :: CREATE AUTOPLAY PLAYLIST
    -- Vytvoří a spustí playlist pro seriál od zadané epizody  ( autoplay režim )
    -- Změna: Playlist se vždy omezí POUZE na aktuální sezónu, bez přeskoků do dalších sezón.
    """

    if addon.getSetting('autolist_enable') == 'false':
        log("PLAYLIST - Funkce globálně deaktivována v nastavení", xbmc.LOGINFO)
        return

    win = xbmcgui.Window(10000)
    if win.getProperty("playto.series_playlist_active") == "true":
        log("PLAYLIST - Playlist already active, skipping re-entry", xbmc.LOGINFO)
        return

    win.setProperty("playto.series_playlist_active", "true")
    log("PLAYLIST - Playlist guard property set", xbmc.LOGINFO)

    playlist = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
    playlist.clear()

    tmdb_id = start_meta.get('tmdb_id')
    tv_show_title = start_meta.get('tv_show_title')

    try:
        start_season_num = int(start_meta.get('season'))
        start_episode_num = int(start_meta.get('episode'))
    except (ValueError, TypeError):
        log(f"PLAYLIST - Neplatná čísla sezóny/epizody : {start_meta.get('season')}/{start_meta.get('episode')}", xbmc.LOGERROR)
        xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', 'PLAYLIST : Neplatná data epizody', xbmcgui.NOTIFICATION_ERROR, 4000)
        xbmcplugin.endOfDirectory(_handle, succeeded=False)
        win.clearProperty("playto.series_playlist_active")
        return

    if not tmdb_id or not tv_show_title:
        xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', 'PLAYLIST : Chybí TMDB ID nebo název seriálu', xbmcgui.NOTIFICATION_ERROR, 4000)
        xbmcplugin.endOfDirectory(_handle, succeeded=False)
        win.clearProperty("playto.series_playlist_active")
        return

    cookies = prehrajto_client.get_premium_cookies()
    items_added = 0

    try:
        max_playlist_items = int(addon.getSetting('autolist_items') or '3')
    except ValueError:
        max_playlist_items = 3

    log(f"PLAYLIST - Začínám vytvářet playlist pro {tv_show_title} (TMDB {tmdb_id}) s limitem {max_playlist_items} epizod. OMEZENO POUZE NA SEZÓNU S{start_season_num:02d}.", xbmc.LOGINFO)

    progress_dialog = xbmcgui.DialogProgress()
    progress_dialog.create('[COLOR orange]·   VYTVÁŘÍM  [ FUCKING ] PLAYLIST   ·[/COLOR]')
    
    current_season_num = start_season_num

    genres_to_set = start_meta.get('genres', [])

    if isinstance(genres_to_set, str):
        genres_to_set = [g.strip() for g in genres_to_set.split(',')]
    elif not isinstance(genres_to_set, list):
        genres_to_set = []

    try:
        if progress_dialog.iscanceled():
            log("PLAYLIST - Uživatelské zrušení playlistu", xbmc.LOGINFO)
            return

        cache_key = f"tv_season_{tmdb_id}_{current_season_num}"
        endpoint = f"tv/{tmdb_id}/season/{current_season_num}"
        log(f"PLAYLIST - Načítám TMDB data sezóny {current_season_num} (cache: {cache_key})", xbmc.LOGINFO)

        try:
            season_data = tmdb_client._fetch(endpoint, params={'language': tmdb_client.language.replace('_', '-')}, cache_key=cache_key)
        except Exception as e:
            log(f"PLAYLIST - CHYBA při načítání TMDB dat : {e}\n{traceback.format_exc()}", xbmc.LOGERROR)
            season_data = None

        if not season_data or not season_data.get('episodes'):
            log(f"PLAYLIST - Žádná data pro sezónu {current_season_num}, ukončuji", xbmc.LOGINFO)
        else:
            episodes = sorted(season_data['episodes'], key=lambda ep: ep.get('episode_number', 0))
            start_index_in_season = 0
            for i, ep in enumerate(episodes):
                if ep.get('episode_number') == start_episode_num:
                    start_index_in_season = i
                    log(f"PLAYLIST - Start od S{current_season_num:02d}E{start_episode_num:02d} (index {i})", xbmc.LOGINFO)
                    break

            for ep in episodes[start_index_in_season:]:
                if progress_dialog.iscanceled() or items_added >= max_playlist_items:
                    break

                ep_num = ep.get('episode_number')
                ep_title = ep.get('name') or f'Epizoda {ep_num}'
                search_query_ep = f"{tv_show_title} S{current_season_num:02d}E{ep_num:02d}"
                log(f"PLAYLIST - Hledám zdroj pro {search_query_ep}", xbmc.LOGINFO)
                results_ep = prehrajto_client.search_sources(search_query_ep, cookies)

                if not results_ep:
                    log(f"PLAYLIST - Žádné výsledky pro {search_query_ep}", xbmc.LOGWARNING)
                    continue

                selected_source = results_ep[0]
                source_link = selected_source['link']

                still_path = ep.get('still_path')
                thumb = f"{tmdb_client.image_base_url}w500{still_path}" if still_path else start_meta.get('poster')
                
                episode_full_meta = {
                    'tmdb_id': tmdb_id,
                    'title': ep_title,
                    'tv_show_title': tv_show_title,
                    'season': current_season_num,
                    'episode': ep_num,
                    'poster': start_meta.get('poster'),
                    'fanart': start_meta.get('fanart'),
                    'genres': genres_to_set,
                    'media_type': 'episode',
                    'plot': ep.get('overview', ''),
                    'rating': ep.get('vote_average', 0.0),
                    'thumb': thumb,
                    'year': ep.get('air_date', '')[:4] if ep.get('air_date') else start_meta.get('year', '')
                }

                playable_url = resolve_video(
                    source_link,
                    cookies,
                    json.dumps(episode_full_meta),
                    return_url_only=True
                )
                
                if not playable_url: #
                    log(f"PLAYLIST - Selhal resolve pro {search_query_ep}", xbmc.LOGWARNING)
                    continue

                li = xbmcgui.ListItem(label=f"S{current_season_num:02d}E{ep_num:02d} - {ep_title}")
                li.setProperty("IsPlayable", "true")

                info_tag = li.getVideoInfoTag()
                info_tag.setMediaType('episode')
                info_tag.setTitle(ep_title)
                info_tag.setPlot(ep.get('overview', ''))
                info_tag.setTvShowTitle(tv_show_title)
                info_tag.setSeason(current_season_num)
                info_tag.setEpisode(ep_num)
                info_tag.setPremiered(ep.get('air_date', ''))
                info_tag.setGenres(genres_to_set)
                
                try:
                    info_tag.setRating(float(ep.get('vote_average', 0.0)))
                except (ValueError, TypeError):
                    info_tag.setRating(0.0)

                li.setArt({
                    'poster': start_meta.get('poster'),
                    'fanart': start_meta.get('fanart'),
                    'thumb': thumb,
                    'icon': thumb
                })
                
                playlist.add(playable_url, li)
                items_added += 1

    except Exception as e:
        log(f"PLAYLIST - Neočekávaná chyba : {e}\n{traceback.format_exc()}", xbmc.LOGERROR)
        xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', 'PLAYLIST : Chyba při vytváření playlistu', xbmcgui.NOTIFICATION_ERROR, 4000)
    finally:
        try:
            progress_dialog.close()
        except:
            pass

    try:
        if items_added > 0:
            xbmc.Player().play(playlist)
            log(f"PLAYLIST - Spouštím playlist s {items_added} epizodami", xbmc.LOGINFO)
        else:
            log("PLAYLIST - Playlist je prázdný, nespouštím", xbmc.LOGWARNING)
            xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', 'PLAYLIST : Nenašel jsem žádné další epizody', xbmcgui.NOTIFICATION_ERROR, 4000)

    except Exception as e:
        log(f"PLAYLIST - Chyba při spouštění playlistu: {e}", xbmc.LOGERROR)

    threading.Timer(2.0, win.clearProperty, args=["playto.series_playlist_active"]).start()


# =======================     M A I N   M E N U   :   PLAY.TO     ======================================================= #
# ======================================================================================================================= #


def menu():
    show_most_watched = addon.getSettingBool('show_most_watched')

    name_list = [
        ('[B][COLOR orange][ HLEDÁNÍ ][/COLOR][/B]', 'listing_search', 'None', '', 'special://home/addons/plugin.video.play_to/resources/icons/SEARCH.png'),
        ('[B][COLOR orange][ HISTORY ][/COLOR][/B]', 'playback_history', 'None', '', 'special://home/addons/plugin.video.play_to/resources/icons/AH.png'),
        ('[B][COLOR orange]·  [/COLOR][/B]FILMY', 'listing_movie_category', 'None', '', 'special://home/addons/plugin.video.play_to/resources/icons/MOVIE.png'),
        ('[B][COLOR orange]·  [/COLOR][/B]SERIÁLY', 'listing_serie_category', 'None', '', 'special://home/addons/plugin.video.play_to/resources/icons/TVSHOW.png'),
        ('[B][COLOR orange]·  [/COLOR][/B]SLEDOVANÉ', 'most_watched', 'None', '', 'special://home/addons/plugin.video.play_to/resources/icons/WATCH.png'),
        ('[B][COLOR orange]·  [/COLOR][/B]TMDB.ORG', 'tmdb_menu', 'None', '', 'special://home/addons/plugin.video.play_to/resources/icons/TMDB.png'),
        ('[B][COLOR orange]·  [/COLOR][/B]TRAKT.TV', 'trakt_menu', 'None', '', 'special://home/addons/plugin.video.play_to/resources/icons/TRAKT-RED.png'),
        ('[B][COLOR orange]·  [/COLOR][/B]TIPY ČSFD', 'list_csfd_daily_tips', 'None', '', 'special://home/addons/plugin.video.play_to/resources/icons/CSFD.png'),
        ('[B][COLOR orange]·  [/COLOR][/B]MANAGER', 'series_menu', 'None', '', 'special://home/addons/plugin.video.play_to/resources/icons/PODCAST.png'),
        ('[B][COLOR orange]·  [/COLOR][/B]SPEEDTEST', 'diagnose_speed', 'None', '', 'special://home/addons/plugin.video.play_to/resources/icons/SPEED.png'),
        ('[B][COLOR limegreen][ NASTAVENÍ ][/COLOR][/B]', 'open_settings', 'None', '', 'special://home/addons/plugin.video.play_to/resources/icons/SETTINGS.png')
    ]


    if not show_most_watched:
        name_list = [item for item in name_list if item[1] != 'most_watched']

    history_exists = history_path and xbmcvfs.exists(history_path)

    for category in name_list:
        label = category[0]
        action = category[1]
        name_param = category[2]
        type_param = category[3]
        icon_path = category[4]

        if not label:
            continue

        list_item = xbmcgui.ListItem(label=label)

        is_folder = True
        if action in ['open_settings', 'diagnose_speed']:
            url = get_url(action=action)
            is_folder = False

        elif action == 'listing_search' and name_param == 'None':
             url = get_url(action=action, name=name_param, type=type_param)
             is_folder = True
        else:
            url = get_url(action=action, name=name_param, type=type_param)

        if icon_path:
            list_item.setArt({'icon': icon_path})

        if action == 'listing_search' and name_param == 'None' and history_exists:

            context_menu = [
                ('[COLOR orange]PLAY : [/COLOR]HISTORIE HLEDÁNÍ',
                 f"ActivateWindow(Videos,{get_url(action='listing_history')},return)")
            ]
            
            list_item.addContextMenuItems(context_menu)
        xbmcplugin.addDirectoryItem(_handle, url, list_item, isFolder=is_folder)

    set_view_mode('files', 'view_mode_main')

    xbmcplugin.endOfDirectory(_handle)



# =======================     ROUTER  |  DISPATCHER     ================================================================= #
# ======================================================================================================================= #



def router(paramstring):

    """
    ROUTER :: MAIN DISPATCHER
    -- Hlavní router funkce, která nyní obsahuje veškerou logiku.
    -- Zpracovává různé akce, inicializuje monitor a udržuje ho při životě.
    """

    # ---------------------------
    #   KONTROLA NÁVRATU
    # ---------------------------

    try:
        params_for_check = dict(parse_qsl(paramstring))
        action_check = params_for_check.get('action')
    except Exception:
        action_check = None

    # if playback_was_active() and action_check in ("find_sources", "create_series_playlist_action", "play"):
    
    if playback_was_active():
        log(f"ROUTER - Detekován návrat z přehrávání (akce={action_check}), router končí", xbmc.LOGINFO)
        clear_playback_flag()
        return

    # ---------------------------
    #   INIT MONITOR
    # ---------------------------
    
    monitor_initialized_by_this_instance = False
    global GLOBAL_TRAKT_MONITOR
    monitor_initialized_flag = "playto.monitor.initialized"

    if GLOBAL_TRAKT_MONITOR is None and not main_window.getProperty(monitor_initialized_flag) == "true":
        try:
            monitor_session = requests.Session()
            GLOBAL_TRAKT_MONITOR = trakt.KodiPlayerMonitor(session=monitor_session, addon=addon, save_playback_history_func=save_playback_history)
            main_window.setProperty(monitor_initialized_flag, "true")
            log("ROUTER - Globální monitor úspěšně inicializován  ( PRVNÍ INSTANCE )", xbmc.LOGINFO)
            monitor_initialized_by_this_instance = True
        except Exception as e:
            log(f"ROUTER - Chyba při inicializaci monitoru : {e}\n{traceback.format_exc()}", xbmc.LOGERROR)
            main_window.clearProperty(monitor_initialized_flag)


    global set_playback_callback
    set_playback_callback = set_playback_started_flag

    # --- ACTIONS : IP CHECK ------------------------------ #
    
    disable_ip_check = addon.getSettingBool('disable_ip_check')
    if not disable_ip_check:
        try:
            allowed, ip_banned, _ = check_run_file()
            if not allowed or ip_banned:
                xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', '[ FUCKING ]  ACCESS DENIED ...', xbmcgui.NOTIFICATION_ERROR, 4000)
                xbmcplugin.endOfDirectory(_handle, succeeded=False)
                return
        except NameError:
             log("ROUTER - Funkce check_run_file() není definována !", xbmc.LOGERROR)
        except Exception as check_e:
             log(f"ROUTER - Chyba při check_run_file(): {check_e}", xbmc.LOGERROR)

    # --- ZPRACOVÁNÍ AKCÍ --------------------------------- #
    
    params = {}
    try:
         params = dict(parse_qsl(paramstring))
    except Exception as e:
         log(f"ROUTER - Chyba při parsování parametrů: {paramstring} -> {e}", xbmc.LOGERROR)

    action = params.get('action')

    if not action:
        menu()
    elif action == 'tmdb_menu':
        tmdb_menu()
    elif action == 'tmdb_login':
        tmdb_account.tmdb_start_auth_flow()
    elif action == 'tmdb_watchlist_movies':
        tmdb_client.list_account_items('watchlist', 'movie', int(params.get('page', 1)))
    elif action == 'tmdb_watchlist_tv':
        tmdb_client.list_account_items('watchlist', 'tv', int(params.get('page', 1)))
    elif action == 'tmdb_rated_movies':
        tmdb_client.list_account_items('rated', 'movie', int(params.get('page', 1)))
    elif action == 'tmdb_rated_tv':
        tmdb_client.list_account_items('rated', 'tv', int(params.get('page', 1)))
    elif action == 'tmdb_favorites_movies':
        tmdb_client.list_account_items('favorites', 'movie', int(params.get('page', 1)))
    elif action == 'tmdb_favorites_tv':
        tmdb_client.list_account_items('favorites', 'tv', int(params.get('page', 1)))
    elif action == 'tmdb_add_watchlist':
        tmdb_account.tmdb_toggle_watchlist(params.get('tmdb_id'), params.get('media_type'), add=True)
        xbmc.executebuiltin('Container.Refresh()')
    elif action == 'tmdb_remove_watchlist':
        tmdb_account.tmdb_toggle_watchlist(params.get('tmdb_id'), params.get('media_type'), add=False)
        xbmc.executebuiltin('Container.Refresh()')
    elif action == 'tmdb_add_favorite':
        tmdb_account.tmdb_toggle_favorite(params.get('tmdb_id'), params.get('media_type'), add=True)
        xbmc.executebuiltin('Container.Refresh()')
    elif action == 'tmdb_remove_favorite':
        tmdb_account.tmdb_toggle_favorite(params.get('tmdb_id'), params.get('media_type'), add=False)
        xbmc.executebuiltin('Container.Refresh()')
    elif action == 'tmdb_rate':
        tmdb_account.tmdb_rate_prompt_and_send(params.get('tmdb_id'), params.get('media_type'))
        xbmc.executebuiltin('Container.Refresh()')
    elif action == 'tmdb_remove_rating':
        tmdb_account.tmdb_remove_rating(params.get('tmdb_id'), params.get('media_type'))
        xbmc.executebuiltin('Container.Refresh()')
    elif action == 'search_tmdb':
        tmdb_client.search(params.get('name'), params.get('type'))
    elif action == 'listing_year_category':
        tmdb_client.list_years_category(params.get('type'))
    elif action == 'listing_year':
        tmdb_client.list_by_year(params.get('page'), params.get('type'), params.get('id'))
    elif action == 'listing_genre_category':
        tmdb_client.list_genres_category(params.get('type'))
    elif action == 'listing_genre':
        tmdb_client.list_by_genre(params.get('page'), params.get('type'), params.get('id'))
    elif action == 'listing_trending':
        tmdb_client.list_trending(params.get('page', '1'), params.get('type'))
    elif action == 'listing_discover':
        tmdb_client.list_discover(params.get('page', '1'), params.get('type'))
    elif action == 'listing_top_rated':
        tmdb_client.list_top_rated(params.get('page', '1'), params.get('type'))
    elif action == 'listing_now_playing':
        tmdb_client.list_now_playing(params.get('page', '1'), params.get('type'))
    elif action == 'listing_upcoming':
        tmdb_client.list_upcoming(params.get('page', '1'), params.get('type'))
    elif action == 'listing_airing_today':
        tmdb_client.list_airing_today(params.get('page', '1'), params.get('type'))
    elif action == 'listing_on_the_air':
        tmdb_client.list_on_the_air(params.get('page', '1'), params.get('type'))
    elif action == 'find_sources':
        prehrajto_client.find_and_list_sources(params.get('meta'))
    elif action == 'listing_tmdb_tv':
        tmdb_client.show_tv_detail(params.get('tmdb_id'), params.get('meta'))
    elif action == 'tmdb_tv_season':
        tmdb_client.show_tv_season(params.get('tmdb_id'), params.get('season'), params.get('meta'))
    elif action == 'play':
        cookies = prehrajto_client.get_premium_cookies()
        meta_param = params.get('meta', '{}')
        resolve_video(params.get('link'), cookies, meta_param)
    elif action == 'create_series_playlist_action':
        try:
            meta_json = params.get('meta')
            if not meta_json:
                raise ValueError("Chybí 'meta' parametr")
            meta_dict = json.loads(meta_json)
            create_series_playlist(meta_dict)
        except Exception as e:
            log(f"| PLAY.TO DEBUG PLAYLIST - Chyba při spouštění playlistu : {e}\n{traceback.format_exc()}", xbmc.LOGERROR)
            xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', f'PLAYLIST : Chyba - {e}', xbmcgui.NOTIFICATION_ERROR, 4000)
            xbmcplugin.endOfDirectory(_handle, succeeded=False)
    elif action == 'most_watched':
        most_watched()
    elif action == 'clear_most_watched_cache':
        try:
            current_category = addon.getSetting('category') or '12 HODIN'
            try:
                current_max_pages = int(addon.getSetting('max_pages') or '2')
                if current_max_pages <= 0: current_max_pages = 2
            except ValueError:
                current_max_pages = 2
            cache_name_to_clear = f"most_watched_{current_category.replace(' ', '_')}_{current_max_pages}"
            cache_dir = _get_cache_dir()
            if cache_dir:
                cache_file_to_clear = os.path.join(cache_dir, f"{cache_name_to_clear}.json")
                if xbmcvfs.exists(cache_file_to_clear):
                    log(f"| PLAY.TO DEBUG CACHE - Mažu cache soubor (podle aktuálního nastavení) : {cache_file_to_clear}", xbmc.LOGINFO)
                    deleted = xbmcvfs.delete(cache_file_to_clear)
                    if deleted:
                        xbmcgui.Dialog().notification('[B][COLOR limegreen]| PLAY.TO |[/COLOR][/B]', f'CACHE  "{current_category}"  Byla vymazána', xbmcgui.NOTIFICATION_INFO, 3000)
                    else:
                         xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', f'CACHE  "{current_category}"  Nepodařilo se smazat', xbmcgui.NOTIFICATION_ERROR, 3000)
                else:
                    log(f"| PLAY.TO DEBUG CACHE - Cache soubor pro smazání (podle aktuálního nastavení) nenalezen: {cache_file_to_clear}", xbmc.LOGINFO)
                    xbmcgui.Dialog().notification('[B][COLOR orange]| PLAY.TO |[/COLOR][/B]', f'CACHE  "{current_category}"  Již neexistuje, nebo nebyla vytvořena', xbmcgui.NOTIFICATION_INFO, 3000)
            else:
                 log("| PLAY.TO DEBUG CACHE - Nelze získat adresář cache pro smazání.", xbmc.LOGERROR)
                 xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', 'CACHE : Nelze získat data', xbmcgui.NOTIFICATION_ERROR, 3000)
            xbmc.executebuiltin('Container.Refresh()')
        except Exception as e:
            log(f"ERROR - Chyba při mazání cache 'Sledované' : {e}\n{traceback.format_exc()}", xbmc.LOGERROR)
            xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', f'CACHE : Chyba pri mazání - {e}', xbmcgui.NOTIFICATION_ERROR, 3000)
    elif action == 'select_csfd':
        handle_csfd_selection(params.get('csfd_id'), params.get('search_type'))
    elif action == 'list_csfd_daily_tips':
        list_csfd_daily_tips()
    elif action == 'trakt_menu':
        session = requests.Session()
        trakt.trakt_menu(params, addon=addon, handle=_handle, session=session)
    elif action == 'trakt_watchlist':
        session = requests.Session()
        trakt.trakt_watchlist(params, addon=addon, handle=_handle, session=session)
    elif action == 'trakt_list_seasons' or action == 'trakt_list_episodes':
        session = requests.Session()
        trakt.list_seasons(params, addon=addon, handle=_handle, session=session) if action == 'trakt_list_seasons' else trakt.list_episodes(params, addon=addon, handle=_handle, session=session)
    elif action == 'trakt_add_to_watchlist':
        session = requests.Session()
        trakt.trakt_add_to_watchlist(params, addon=addon, handle=_handle, session=session)
    elif action == 'trakt_popular_lists':
        session = requests.Session()
        trakt.trakt_popular_lists(params, addon=addon, handle=_handle, session=session)
    elif action == 'trakt_recommended':
        session = requests.Session()
        trakt.trakt_recommended(params, addon=addon, handle=_handle, session=session)
    elif action == 'trakt_trending':
        session = requests.Session()
        trakt.trakt_trending(params, addon=addon, handle=_handle, session=session)
    elif action == 'trakt_genres':
        session = requests.Session()
        trakt.trakt_genres(params, addon=addon, handle=_handle, session=session) #
    elif action == 'listing_search':
        search(params.get('name'))
    elif action == 'find_meta_and_resolve':
        search(params.get('title'), resolve_first=True)
    elif action == 'listing_history':
        listing_history()
    elif action == 'delete_search_history_item':
        delete_search_history_item(params)
    elif action == 'clear_search_history':
        clear_search_history()
    elif action == 'playback_history':
        playback_history()
    elif action == 'playback_show_history':
        playback_show_history(params)
    elif action == 'remove_playback_item':
        remove_playback_item(params)
    elif action == 'clear_playback_history':
        clear_playback_history()
    elif action == 'listing_movie_category':
        movie_category()
    elif action == 'listing_serie_category':
        serie_category()
    elif action == 'library':
        current_library_path = _get_path_and_ensure_dir(SETTING_ID_LIBRARY_DIR, DEFAULT_LIBRARY_DIR)
        if not current_library_path:
            xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', 'LIBRARY : Cesta pro knihovnu není nastavena nebo ji nelze vytvořit', xbmcgui.NOTIFICATION_ERROR, 4000)
            return
        parsed_url_path = urlparse(params.get('url', '')).path
        name_from_url = parsed_url_path.split('/')[-1] if '/' in parsed_url_path else 'unknown_video'
        default_name = os.path.splitext(name_from_url)[0].replace('-', ' ')
        kb = xbmc.Keyboard(default_name, '[COLOR orange]·   ZADEJTE NÁZEV A ROK  [ FUCKING ]  FILMU / SERIÁLU   ·[/COLOR]')
        kb.doModal()
        if kb.isConfirmed():
            user_input_name = kb.getText().strip()
            if user_input_name:
                safe_filename = "".join(c if c.isalnum() or c in (' ', '-', '_', '.') else '_' for c in user_input_name).rstrip(' .') # type: ignore
                strm_filename = f"{safe_filename}.strm"
                strm_filepath = os.path.join(current_library_path, strm_filename)
                if xbmcvfs.exists(strm_filepath):
                    xbmcgui.Dialog().notification('[B][COLOR orange]| PLAY.TO |[/COLOR][/B]', 'LIBRARY : Soubor již existuje', xbmcgui.NOTIFICATION_WARNING, 3000)
                else:
                    strm_content = f'plugin://plugin.video.play_to/?action=play&link={params.get("url", "")}'
                    file_handle = None
                    try:
                        file_handle = xbmcvfs.File(strm_filepath, 'w')
                        bytes_written = file_handle.write(strm_content)
                        if bytes_written == 0 and strm_content:
                             raise IOError("Nepodařilo se zapsat do .strm souboru (0 bytes)")
                        xbmcgui.Dialog().notification('[B][COLOR limegreen]| PLAY.TO |[/COLOR][/B]', 'LIBRARY : Úspěšně uloženo', xbmcgui.NOTIFICATION_INFO, 3000, sound=False)
                    except Exception as write_e:
                         log(f"LIBRARY - Chyba při zápisu .strm souboru: {write_e}\n{traceback.format_exc()}", xbmc.LOGERROR)
                         xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', 'LIBRARY : Chyba při ukládání souboru', xbmcgui.NOTIFICATION_ERROR, 4000)
                    finally:
                         if file_handle: file_handle.close()
    elif action == 'download':
        current_download_path = _get_path_and_ensure_dir(SETTING_ID_DOWNLOAD_DIR, DEFAULT_DOWNLOAD_DIR)
        if not current_download_path:
            xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', 'DOWNLOAD : Cesta pro stahování není nastavena nebo ji nelze vytvořit', xbmcgui.NOTIFICATION_ERROR, 4000)
            return
        dialog = None
        final_filepath = None
        subtitle_filepath = None
        try:
             source_url = params.get('url', '')
             if not source_url: raise ValueError("Chybí URL pro stahování")
             resp = safe_get(session, source_url, headers=prehrajto_client.headers, timeout=15)
             page_content = resp.content if resp is not None else None
             file_url, subtitle_url = prehrajto_client.get_video_link(page_content) if page_content else (None, None)
             if not file_url:
                 raise ValueError("Nepodařilo se získat odkaz na video soubor")
             parsed_orig_path = urlparse(source_url).path
             base_name = parsed_orig_path.split('/')[-1] if '/' in parsed_orig_path else 'downloaded_video'
             base_name = os.path.splitext(base_name)[0].replace('-', '_')
             parsed_file_path = urlparse(file_url).path # type: ignore
             file_ext = os.path.splitext(parsed_file_path)[1] if '.' in os.path.basename(parsed_file_path) else '.mp4'
             download_name = f"{base_name}{file_ext}"
             final_filepath = os.path.join(current_download_path, download_name)
             if subtitle_url:
                 try:
                     subtitle_name = f"{base_name}.srt"
                     subtitle_filepath = os.path.join(current_download_path, subtitle_name)
                     sub_resp = safe_get(session, subtitle_url, timeout=10)
                     subtitle_content = sub_resp.content if sub_resp is not None else None
                     sub_file_handle = None
                     try:
                         sub_file_handle = xbmcvfs.File(subtitle_filepath, 'wb')
                         sub_file_handle.write(subtitle_content)
                         log(f"DOWNLOAD - Titulky uloženy: {subtitle_name}", xbmc.LOGINFO)
                     finally:
                          if sub_file_handle: sub_file_handle.close()
                 except Exception as sub_e:
                      log(f"DOWNLOAD - Chyba stahování titulků: {sub_e}", xbmc.LOGERROR)
                      subtitle_filepath = None
             cookies = prehrajto_client.get_premium_cookies()
             if cookies:
                 try:
                     res_premium = safe_get(session, f"{source_url}?do=download", cookies=cookies, headers=prehrajto_client.headers, allow_redirects=False, timeout=10)
                     if res_premium and res_premium.status_code in [301, 302, 303, 307, 308] and 'Location' in res_premium.headers:
                         file_url = res_premium.headers['Location']
                         log("DOWNLOAD - Používám premium odkaz.", xbmc.LOGINFO)
                 except Exception as prem_e:
                      log(f"DOWNLOAD - Chyba získání premium odkazu (pokračuji s normálním): {prem_e}", xbmc.LOGWARNING)
             dialog = xbmcgui.DialogProgress()
             dialog.create('[B][COLOR limegreen]| PLAY.TO |[/COLOR][/B]', f'DOWNLOAD : {download_name}\nDO : {current_download_path}') # --- DOWNLOAD :  ( type: ignore )
             res_download = safe_get(session, file_url, stream=True, timeout=30, headers=prehrajto_client.headers)
             if res_download is None:
                 raise requests.exceptions.RequestException('Failed to start download (network error)')
             file_size = int(res_download.headers.get('Content-Length', 0))
             start_time = time.time()
             file_size_dl = 0
             block_sz = 8192 * 4
             dl_file_handle = None
             try:
                 dl_file_handle = xbmcvfs.File(final_filepath, 'wb')
                 for chunk in res_download.iter_content(chunk_size=block_sz):
                     if dialog.iscanceled():
                         log("DOWNLOAD - Stahování zrušeno uživatelem.", xbmc.LOGINFO)
                         return
                     if chunk:
                         bytes_written = dl_file_handle.write(chunk)
                         if bytes_written == 0:
                              raise IOError("Zápis na disk selhal (0 bytes zapsáno)")
                         file_size_dl += len(chunk)
                         if file_size > 0:
                             percent = int(file_size_dl * 100 / file_size)
                             elapsed = time.time() - start_time
                             speed_mbps = (file_size_dl / (elapsed * 1024 * 1024)) if elapsed > 0 else 0 # type: ignore
                             status_line1 = f'Velikost: {files.convert_size(file_size)} Staženo: {percent}%'
                             status_line2 = f'Rychlost: {speed_mbps:.2f} MB/s'
                             status_line3 = download_name
                             dialog.update(percent, f'{status_line1}\n{status_line2}\n{status_line3}')
                         else:
                             status_line1 = f'Staženo: {files.convert_size(file_size_dl)}'
                             status_line2 = download_name
                             dialog.update(0, f'{status_line1}\n{status_line2}')
                 xbmcgui.Dialog().notification('[B][COLOR limegreen]| PLAY.TO |[/COLOR][/B]', f'DOWNLOAD : Stahování dokončeno\n{download_name}', xbmcgui.NOTIFICATION_INFO, 5000)
             finally:
                  if dl_file_handle: dl_file_handle.close()
        except requests.exceptions.Timeout:
             log("DOWNLOAD - Timeout při stahování.", xbmc.LOGERROR)
             xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', 'DOWNLOAD : Timeout při stahování', xbmcgui.NOTIFICATION_ERROR, 5000)
        except requests.exceptions.RequestException as req_e:
             log(f"DOWNLOAD - Chyba sítě: {req_e}", xbmc.LOGERROR)
             xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', f'DOWNLOAD : Chyba sítě - {req_e}', xbmcgui.NOTIFICATION_ERROR, 5000)
        except IOError as io_e:
             log(f"DOWNLOAD - Chyba zápisu na disk: {io_e}", xbmc.LOGERROR)
             xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', f'DOWNLOAD : Chyba zápisu - {io_e}', xbmcgui.NOTIFICATION_ERROR, 5000)
        except ValueError as val_e:
             log(f"DOWNLOAD - Chyba vstupu: {val_e}", xbmc.LOGERROR)
             xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', f'DOWNLOAD : Chyba - {val_e}', xbmcgui.NOTIFICATION_ERROR, 5000)
        except Exception as e:
             log(f"DOWNLOAD - Neočekávaná chyba: {e}\n{traceback.format_exc()}", xbmc.LOGERROR)
             xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', f'DOWNLOAD : Neočekávaná chyba - {e}', xbmcgui.NOTIFICATION_ERROR, 5000)
        finally:
             if dialog and dialog.iscanceled():
                 if final_filepath and xbmcvfs.exists(final_filepath):
                     try:
                         xbmcvfs.delete(final_filepath)
                         log(f"DOWNLOAD - Nekompletní soubor smazán: {final_filepath}", xbmc.LOGINFO)
                     except Exception as del_e:
                          log(f"DOWNLOAD - Chyba při mazání nekompletního souboru: {del_e}", xbmc.LOGERROR)
                 if subtitle_filepath and xbmcvfs.exists(subtitle_filepath):
                     try:
                         xbmcvfs.delete(subtitle_filepath)
                         log(f"DOWNLOAD - Soubor titulků smazán: {subtitle_filepath}", xbmc.LOGINFO)
                     except Exception as del_sub_e:
                          log(f"DOWNLOAD - Chyba při mazání souboru titulků: {del_sub_e}", xbmc.LOGERROR)
             if dialog:
                 try:
                     dialog.close()
                 except:
                     pass
    elif action == 'search_title':
        search_term = params.get('name', '')
        kb = xbmc.Keyboard(search_term, '[COLOR orange]·   HLEDAT  [ FUCKING ]  TITUL   ·[/COLOR]')
        kb.doModal()
        if kb.isConfirmed():
            q = kb.getText().strip()
            if q:
                plugin_url = f"{_url}?action=listing_search&name={quote(q)}"
                xbmc.executebuiltin(f'Container.Update({plugin_url})')
    elif action == 'open_settings':
        xbmc.executebuiltin('Addon.OpenSettings(plugin.video.play_to)')
    elif action == 'diagnose_speed':
        speedtest.diagnose_speed(addon)
    elif action == 'series_menu':
        create_series_menu()
    elif action == 'series_search':
        kb = xbmc.Keyboard('', '[COLOR orange]·   ZADEJTE NÁZEV  [ FUCKING ]  SERIÁLU   ·[/COLOR]')
        kb.doModal()
        if kb.isConfirmed():
            series_name = kb.getText().strip()
            if series_name:
                cookies = prehrajto_client.get_premium_cookies()
                series_manager.search_series(series_name, cookies)
                xbmc.executebuiltin('Container.Refresh()')
    elif action == 'series_refresh':
        cookies = prehrajto_client.get_premium_cookies()
        series_manager.search_series(params.get('series_name'), cookies)
        xbmc.executebuiltin('Container.Refresh()')
    elif action == 'series_detail':
        create_seasons_menu(params.get('series_name'))
    elif action == 'series_season':
        create_episodes_menu(params.get('series_name'), params.get('season'))
    elif action == 'series_delete':
        if series_manager.delete_series(params.get('series_name')):
             xbmc.executebuiltin('Container.Refresh()')
    elif action == 'season_delete':
        if series_manager.delete_season(params.get('series_name'), params.get('season')):
            xbmc.executebuiltin('Container.Refresh()')
    elif action == 'episode_delete':
        if series_manager.delete_episode(params.get('series_name'), params.get('season'), params.get('episode')):
            xbmc.executebuiltin('Container.Refresh()')
    elif action == 'episode_mark_watched':
        series_manager.mark_episode_watched(params.get('series_name'), params.get('season'), params.get('episode'))
        xbmc.executebuiltin('Container.Refresh()')
    elif action == 'episode_mark_unwatched':
        series_manager.mark_episode_unwatched(params.get('series_name'), params.get('season'), params.get('episode'))
        xbmc.executebuiltin('Container.Refresh()')
    elif action:
         log(f"ROUTER - Neznámá akce : {action}", xbmc.LOGWARNING)

    # ---------------------------
    #   MONITORU KEEP-ALIVE
    # ---------------------------

    if not playback_started_internally and monitor_initialized_by_this_instance:
        monitor = xbmc.Monitor()
        log("ROUTER - Vstupuji do keep-alive smyčky  ( monitor inicializován, ale bez přehrávání )", xbmc.LOGINFO)
        while not monitor.abortRequested():
            if monitor.waitForAbort(1):
                break
        log("ROUTER - Keep-alive smyčka ukončena", xbmc.LOGINFO)
        try:
            main_window.clearProperty(monitor_initialized_flag)
            log("ROUTER - Příznak inicializace monitoru vyčištěn", xbmc.LOGINFO)
        except NameError:
            pass
    else:
        log(
            f"ROUTER - Přeskakuji keep-alive smyčku  ( Akce='{action}', "
            f"Přehrávání={playback_started_internally}, "
            f"InstanceInit={monitor_initialized_by_this_instance} )",
            xbmc.LOGINFO
        )
