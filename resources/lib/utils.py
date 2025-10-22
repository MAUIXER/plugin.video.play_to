# -*- coding: utf-8 -*-


# =========================================================================
#
#  Module: utils
#  Author: Mau!X ER
#  Created on: 20.10.2025
#  License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
# =========================================================================



import xbmc
import xbmcgui
import xbmcaddon

import re
import math
import unicodedata

from urllib.parse import urlencode
import requests
from requests.exceptions import RequestException




# =======================     GLOBAL LOGGING CONTROL     ============================================================== #
# ===================================================================================================================== # 


try:
    _ADDON = xbmcaddon.Addon()
    _LOG_LEVEL_INDEX = int(_ADDON.getSetting('logging_level') or '0')

except Exception:
    _LOG_LEVEL_INDEX = 0




_LEVEL_MAP = {
    0: xbmc.LOGDEBUG,
    1: xbmc.LOGINFO,
    2: xbmc.LOGWARNING,
    3: xbmc.LOGERROR,
    4: xbmc.LOGNONE,
}



_MIN_LOG_LEVEL = _LEVEL_MAP.get(_LOG_LEVEL_INDEX, xbmc.LOGDEBUG)


# ---------------------------------------------------------------------------------------------------------------------- #


def log(message, level=xbmc.LOGDEBUG):

    """
    GLOBAL :: LOG CONTROL
    -- Globální logovací funkce. Zpráva je vydána, pokud je její úroveň  ( level ) 
    -- vyšší nebo rovna nastavené minimální úrovni  ( _MIN_LOG_LEVEL )
    """

    global _MIN_LOG_LEVEL

    if level >= _MIN_LOG_LEVEL:
        xbmc.log(f"| PLAY.TO :: {message}", level=level)



# =======================     GLOBAL LOGGING CONTROL     ============================================================== #
# ===================================================================================================================== # 



def get_url(**kwargs):
    return f"plugin://plugin.video.play_to/?{urlencode(kwargs)}"



def popinfo(message, title="[B][COLOR orange]| PLAY.TO |[/COLOR][/B]", time=5000, icon=xbmcgui.NOTIFICATION_INFO, sound=False):
    xbmcgui.Dialog().notification(title, message, icon, time, sound)



def encode(string):
    line = unicodedata.normalize('NFKD', string)
    output = ''
    for c in line:
        if not unicodedata.combining(c):
            output += c
    return output



def convert_size_to_bytes(size_str):
    size_str = size_str.replace(',', '.').upper().strip()
    match = re.match(r'([\d\.]+)\s*(KB|MB|GB|TB)', size_str)
    if not match:
        return 0
    size, unit = float(match.group(1)), match.group(2)
    factor = {'KB': 1024, 'MB': 1024 ** 2, 'GB': 1024 ** 3, 'TB': 1024 ** 4}
    return size * factor.get(unit, 0)



def convert_size(size_bytes):
    if not isinstance(size_bytes, (int, float)) or size_bytes <= 0:
        return "0 B"
    size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"



def duration_to_seconds(duration_str):
    if not duration_str:
        return 0
    try:
        parts = duration_str.strip().split(':')
        if len(parts) == 3:
            h, m, s = list(map(int, parts))
            return h * 3600 + m * 60 + s
        elif len(parts) == 2:
            m, s = list(map(int, parts))
            return m * 60 + s
        return 0
    except (ValueError, TypeError):
        return 0


# ----------------------
# Centralized HTTP helpers
# ----------------------
DEFAULT_HTTP_TIMEOUT = 15


def safe_get(session_or_url, url=None, timeout=None, **kwargs):
    """Safe GET helper. Accepts either (session, url) or (url) where session_or_url is requests.Session or a URL string.
    Returns Response or None on error.
    """
    _timeout = timeout or DEFAULT_HTTP_TIMEOUT
    try:
        if url is None:
            # called as safe_get(url=..., ...)
            resp = requests.get(session_or_url, timeout=_timeout, **kwargs)
        else:
            session = session_or_url
            resp = session.get(url, timeout=_timeout, **kwargs)
        resp.raise_for_status()
        return resp
    except RequestException as e:
        try:
            log(f"HTTP GET error for {url or session_or_url}: {e}", level=xbmc.LOGERROR)
        except Exception:
            pass
        return None


def safe_post(session_or_url, url=None, timeout=None, **kwargs):
    """Safe POST helper. Accepts either (session, url) or (url) where session_or_url is requests.Session or a URL string.
    Returns Response or None on error.
    """
    _timeout = timeout or DEFAULT_HTTP_TIMEOUT
    try:
        if url is None:
            resp = requests.post(session_or_url, timeout=_timeout, **kwargs)
        else:
            session = session_or_url
            resp = session.post(url, timeout=_timeout, **kwargs)
        resp.raise_for_status()
        return resp
    except RequestException as e:
        try:
            log(f"HTTP POST error for {url or session_or_url}: {e}", level=xbmc.LOGERROR)
        except Exception:
            pass
        return None



# ================================================================================== #
# ===================    D E S C E N T  --  C L E A N E R    ======================= #
# ================================================================================== #



def clean_title_for_tmdb(title):
    log(f"UTILS CLEAN - VSTUP : '{title}'", level=xbmc.LOGINFO)


    search_title = title


    # --- normalizace znaků a odstranění diakritiky

    search_title = search_title.replace('_', ' ').replace('.', ' ').replace('+', ' ')
    search_title = encode(search_title)


    # --- extrakce sezóny a epizody SxxExx nebo rozsah S01E02-08

    season = None
    episode = None
    ep_end = None
    ep_match = re.search(r'\b[Ss](\d{1,2})[Ee](\d{1,2})(?:-(\d{1,2}))?\b', search_title)
    if ep_match:
        season = int(ep_match.group(1))
        episode = int(ep_match.group(2))
        ep_end = int(ep_match.group(3)) if ep_match.group(3) else None
        search_title = re.sub(re.escape(ep_match.group(0)), '', search_title, flags=re.IGNORECASE)


    # --- extrakce roku (19xx, 20xx) pokud je na konci nebo před SxxExx

    year_match = re.search(r'\b(19[89]\d|20\d\d)\b', search_title)
    year = year_match.group(1) if year_match else None
    if year:
        search_title = re.sub(r'\b' + year + r'\b', '', search_title)


    # --- odstranění “junk slov”

    junk_words = [
        'cz', 'czdab', 'dab', 'dabing', 'czaudio', 'dd', 'hevc',
        '1080p', '720p', '2160p', '4k', 'hd', 'fullhd', 'ultra hd', 'uhd',
        'topkvalita', 'web-dl', 'webrip', 'bluray', 'dvdrip',
        'final', 'komplet', 'x264', 'x265', 'amzn'
    ]
    pattern = r'\b(?:' + '|'.join(junk_words) + r')\b'
    search_title = re.sub(pattern, '', search_title, flags=re.IGNORECASE)


    # --- odstranění závorek a vícenásobných mezer

    search_title = re.sub(r'[\(\[\{].*?[\)\]\}]', '', search_title)
    search_title = re.sub(r'\s+', ' ', search_title).strip()



    log(f"UTILS CLEAN - VÝSTUP : '{search_title}', ROK : '{year}', SEZÓNA : '{season}', EPIZODA : '{episode}', EP_END : '{ep_end}'", level=xbmc.LOGINFO)
    
    return search_title, year, season, episode, ep_end


    # --- DEFAULT : QUERY
    #
    # return search_title, year


# ===================    D E S C E N T  --  C L E A N E R    ======================= #
# ================================================================================== #



# def clean_title_for_tmdb(title):
#    log = xbmc.log  # Kodi log
#
#    log(f"CLEAN - VSTUP : '{title}'", level=xbmc.LOGINFO)
#
#    # --- normalizace znaků
#    search_title = re.sub(r'[_.:\-–…\[\]\(\)]', ' ', title)
#    search_title = search_title.replace('+', ' ')
#
#    # --- extrakce roku
#    year = None
#    year_match = re.search(r'\b(19[89]\d|20\d\d)\b', search_title)
#    if year_match:
#        year = year_match.group(1)
#        search_title = search_title.replace(year, '')
#
#    # --- extrakce sezóny a epizody (SxxExx nebo SxxExx-xx)
#    season = None
#    episode = None
#    ep_match = re.search(r'\bS(\d{1,2})E(\d{1,2})(?:-(\d{1,2}))?\b', search_title, re.IGNORECASE)
#    if ep_match:
#        season = int(ep_match.group(1))
#        episode = int(ep_match.group(2))
#        search_title = re.sub(re.escape(ep_match.group(0)), '', search_title, flags=re.IGNORECASE)
#
#    # --- odstranění junk slov
#    junk_words = [
#        'czdab', 'cz tit', 's dabingom', 'cz', 'dabing', 'titulky', 'sk dab', 'eng',
#        '1080p', '720p', '2160p', '4k', 'hd', 'fullhd', 'ultra hd', 'uhd', 'topkvalita',
#        'web-dl', 'webrip', 'web dl', 'bluray', 'dvdrip', 'final', 'komplet',
#        'x264', 'x265', 'rarbg', 'amzn', 'czaudio', 'dd', 'hdr'
#    ]
#    junk_pattern = r'\b(?:' + '|'.join(junk_words) + r')\b'
#    search_title = re.sub(junk_pattern, '', search_title, flags=re.IGNORECASE)
#
#    # --- odstranění vícenásobných mezer, trim
#    search_title = ' '.join(search_title.split())
#
#    log(f"CLEAN - VÝSTUP : '{search_title}', ROK : '{year}', SEZÓNA : '{season}', EPIZODA : '{episode}'", level=xbmc.LOGINFO)
#    return search_title, year, season, episode



# --- : DEFAULT
#
# def clean_title_for_tmdb(title):
#    log(f"CLEAN - VSTUP : '{title}'", level=xbmc.LOGINFO)
#    search_title = re.sub(r'[_.:\-–…\[\]()]', ' ', title)
#    year = None
#    series_match = re.search(r'\b[sS](\d{1,2})[eE](\d{1,2})\b', search_title)
#    if series_match:
#        search_title = search_title.split(series_match.group(0))[0].strip()
#    year_match = re.search(r'\b(19[89]\d|20\d\d)\b', search_title)
#    if year_match:
#        year = year_match.group(1)
#        search_title = search_title.replace(year, '')
#    junk_words = ['czdab', 'cz tit', 's dabingom', 'cz', 'dabing', 'titulky', 'sk dab', 'eng', '1080p', '720p', '2160p', '4k', 'hd', 'fullhd', 'ultra hd', 'uhd', 'topkvalita', 'web-dl', 'webrip', 'web dl', 'bluray', 'dvdrip', 'final', 'komplet', 'x264', 'x265', 'rarbg']
#    junk_pattern = r'\b(' + '|'.join(junk_words) + r')\b'
#    search_title = re.sub(junk_pattern, '', search_title, flags=re.IGNORECASE)
#    search_title = ' '.join(search_title.split())
#    log(f"CLEAN - VÝSTUP : '{search_title}', ROK : '{year}'", level=xbmc.LOGINFO)
#    return search_title, year
