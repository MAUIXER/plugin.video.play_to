# -*- coding: utf-8 -*-


# =========================================================================
#
#  Module: tmdb_account
#  Author: Mau!X ER
#  Created on: 20.10.2025
#  License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
# =========================================================================



import os
import sys
import json
import requests

from urllib.parse import urlencode


from resources.lib.utils import log, popinfo, safe_get, safe_post


try:
    import xbmc
    import xbmcgui
    import xbmcvfs
    import xbmcaddon
    import xbmcplugin
    _is_kodi = True

except ImportError:
    _is_kodi = False

    # --- MOCK TESTS : Kodi modules for testing outside of Kodi

    class _MockAddon:
        def getSetting(self, id): return ""
        def getAddonInfo(self, id): return f"mock.{id}"
    class _MockDialog:
        def ok(self, *args, **kwargs): pass
        def yesno(self, *args, **kwargs): return False
        def notification(self, *args, **kwargs): pass
    class _MockXbmcGui:
        Dialog = _MockDialog
        NOTIFICATION_INFO = 0
        NOTIFICATION_ERROR = 1
    xbmcaddon = type('xbmcaddon', (object,), {'Addon': _MockAddon})
    xbmcgui = _MockXbmcGui()




ADDON = xbmcaddon.Addon()
API_KEY = ADDON.getSetting('api_key')
LANGUAGE = ADDON.getSetting('tmdb_language') or 'cs_CZ'
BASE_URL = 'https://api.themoviedb.org/3'
SESSION = requests.Session()




if _is_kodi:
    ACCOUNT_DIR = xbmcvfs.translatePath(ADDON.getAddonInfo('profile'))
else:
    ACCOUNT_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'temp')
ACCOUNT_FILE = os.path.join(ACCOUNT_DIR, 'tmdb_account.json')





# ---------------------------------------------------------------------
# --                    TMDB  --  Pomocné funkce
# ---------------------------------------------------------------------


def _ensure_account_dir_exists():
    exists_func = xbmcvfs.exists if _is_kodi else os.path.exists
    mkdir_func = xbmcvfs.mkdir if _is_kodi else os.makedirs
    if not exists_func(ACCOUNT_DIR):
        try:
            mkdir_func(ACCOUNT_DIR)
            log(f"TMDB - Vytvořen adresář pro účet : {ACCOUNT_DIR}", level=xbmc.LOGINFO)
            return True
        except Exception as e:
            log(f"TMDB - CHYBA : Nelze vytvořit adresář pro účet : {e}", level=xbmc.LOGERROR)
            return False
    return True



def save_account_data(data):
    if not _ensure_account_dir_exists():
        log(f"TMDB - CHYBA při ukládání : Adresář neexistuje", level=xbmc.LOGERROR)
        return
    f = None
    try:
        f = xbmcvfs.File(ACCOUNT_FILE, 'w')
        f.write(json.dumps(data, ensure_ascii=False, indent=2))
        log(f"TMDB - Data účtu úspěšně uložena do : {ACCOUNT_FILE}", level=xbmc.LOGINFO)
    except Exception as e:
        log(f"TMDB - CHYBA při ukládání dat účtu : {e}", level=xbmc.LOGERROR)
    finally:
        if f:
            f.close()



def load_account_data():
    exists_func = xbmcvfs.exists if _is_kodi else os.path.exists
    if not exists_func(ACCOUNT_FILE):
        return {}
    f = None
    try:
        f = xbmcvfs.File(ACCOUNT_FILE, 'r')
        content = f.read()
        return json.loads(content) if content else {}
    except Exception as e:
        log(f"TMDB - CHYBA při načítání dat účtu  ( reset ) : {e}", level=xbmc.LOGERROR)
        return {}


# ---------------------------------------------------------------------
# --                  TMDB OAUTH  –  přihlášení
# ---------------------------------------------------------------------


def tmdb_start_auth_flow():
    try:
        # use timeout to prevent blocking
        res = safe_get(f'{BASE_URL}/authentication/token/new', params={'api_key': API_KEY}, timeout=10)
        if res is None:
            raise Exception('Network error while requesting token')
        res.raise_for_status()
        token = res.json().get('request_token')
        if not token:
            raise Exception('Token not received')

        auth_url = f'https://www.themoviedb.org/authenticate/{token}'

        log(f"TMDB  -  AUTH URL : {auth_url}", xbmc.LOGINFO)
        xbmcgui.Dialog().ok("[COLOR orange][ FUCKING ] TMDB PŘIHLAŠOVÁNÍ[/COLOR]", f"[B][COLOR orange]·  [/COLOR]OTEVŘI ODKAZ V PROHLÍŽEČI A POTVRĎ PŘÍSTUP[/B]\n[B][COLOR orange]·  [/COLOR]URL MŮŽEŠ ZKOPÍROVAT ZE SOUBORU  [ kodi.log ][/B]\n\n{auth_url}")

        if xbmcgui.Dialog().yesno("[COLOR orange][ FUCKING ] TMDB PŘIHLAŠOVÁNÍ[/COLOR]", "\n[B][COLOR orange]·  [/COLOR]POTVRDIL JSI PŘÍSTUP NA WEBU TMDB ?[/B]"):
            session_res = safe_post(f'{BASE_URL}/authentication/session/new', params={'api_key': API_KEY}, json={'request_token': token}, timeout=10)
            session_res.raise_for_status()
            session_id = session_res.json().get('session_id')
            if not session_id:
                raise Exception('Chybí session_id')

            # --- TMDB : Získat účet

            acc_res = safe_get(f'{BASE_URL}/account', params={'api_key': API_KEY, 'session_id': session_id}, timeout=10)
            acc_res.raise_for_status()
            account_data = acc_res.json()
            account_data['session_id'] = session_id
            save_account_data(account_data)

            xbmcgui.Dialog().notification('[B][COLOR orange]| PLAY.TO |[/COLOR][/B]', f"TMDB : Přihlášen jako : {account_data.get('username')}", xbmcgui.NOTIFICATION_INFO, 5000)
    except Exception as e:
        xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', f"TMDB : Chyba přihlášení : {e}", xbmcgui.NOTIFICATION_ERROR, 5000)


# ---------------------------------------------------------------------
# --        Výpis seznamů  ( watchlist, rated, favorites )
# ---------------------------------------------------------------------


def _make_tmdb_request(endpoint_template, media_type, page=1, method='GET', payload=None):
    data = load_account_data()
    session_id = data.get('session_id')
    if not session_id:
        xbmcgui.Dialog().notification("[B][COLOR red]| PLAY.TO |[/COLOR][/B]", "TMDB : Nejsi přihlášen !", xbmcgui.NOTIFICATION_ERROR, 3000)
        return None

    account_id = data.get('id')
    media_endpoint = 'movies' if media_type == 'movie' else 'tv'
    url = f"{BASE_URL}/account/{account_id}/{endpoint_template.format(media_endpoint=media_endpoint)}"
    
    params = {
        'api_key': API_KEY,
        'session_id': session_id,
        'language': LANGUAGE.replace('_', '-')
    }
    if method == 'GET':
        params['page'] = page
        params['sort_by'] = 'created_at.desc'

    try:
        if method == 'GET':
            res = safe_get(SESSION, url, params=params, timeout=15)
        elif method == 'POST':
            res = safe_post(SESSION, url, params=params, json=payload, timeout=15)
        else:
            log(f"TMDB - Nepodporovaná metoda : {method}", level=xbmc.LOGERROR)
            return None

        res.raise_for_status()
        return res.json()

    except requests.exceptions.RequestException as e:
        log(f"TMDB - Chyba API volání na {url}: {e}", level=xbmc.LOGERROR)
        xbmcgui.Dialog().notification("[B][COLOR red]| PLAY.TO |[/COLOR][/B]", f"TMDB : Chyba komunikace s TMDB : {e}", xbmcgui.NOTIFICATION_ERROR, 4000)
        return None



def tmdb_get_watchlist(media_type='movie', page=1):
    return _make_tmdb_request("watchlist/{media_endpoint}", media_type, page)



def tmdb_get_rated(media_type='movie', page=1):
    return _make_tmdb_request("rated/{media_endpoint}", media_type, page)



def tmdb_get_favorites(media_type='movie', page=1):
    return _make_tmdb_request("favorite/{media_endpoint}", media_type, page)



def _toggle_tmdb_list(list_name, tmdb_id, media_type, add=True):
    data = load_account_data()
    session_id = data.get('session_id')
    if not session_id:
        xbmcgui.Dialog().notification("[B][COLOR red]| PLAY.TO |[/COLOR][/B]", "TMDB : Nejsi přihlášen !", xbmcgui.NOTIFICATION_ERROR, 3000)
        return

    account_id = data.get('id')
    payload = {'media_type': media_type, 'media_id': int(tmdb_id), list_name: add}
    url = f"{BASE_URL}/account/{account_id}/{list_name}"
    params = {'api_key': API_KEY, 'session_id': session_id}

    try:
        res = safe_post(SESSION, url, params=params, json=payload, timeout=15)
        if res is None:
            raise requests.exceptions.RequestException('Network error')
        res.raise_for_status()

        # ---TMDB : API vrací 201 pro přidání a 200 pro odebrání  ( někdy i 1 pro úspěch v status_message )

        response_data = res.json()
        if response_data.get('success') or response_data.get('status_code') in [1, 12, 13]:
            list_name_cz = "WATCHLISTU" if list_name == "watchlist" else "OBLÍBENÝCH"
            action_cz = "TMDB : PŘIDÁNO DO" if add else "TMDB : ODEBRÁNO Z"
            msg = f"{action_cz} {list_name_cz}"
            xbmcgui.Dialog().notification("[B][COLOR orange]| PLAY.TO |[/COLOR][/B]", msg, xbmcgui.NOTIFICATION_INFO, 3000)
        else:
            raise ValueError(f"API nevrátilo úspěch: {response_data.get('status_message', 'Neznámá chyba')}")

    except requests.exceptions.RequestException as e:
        log(f"TMDB - Chyba API při úpravě seznamu {list_name}: {e}", level=xbmc.LOGERROR)
        xbmcgui.Dialog().notification("[B][COLOR red]| PLAY.TO |[/COLOR][/B]", f"TMDB : Chyba při úpravě seznamu {list_name}", xbmcgui.NOTIFICATION_ERROR, 3000)
    except ValueError as e:
        log(f"TMDB - Chyba API odpovědi při úpravě seznamu {list_name}: {e}", level=xbmc.LOGERROR)
        xbmcgui.Dialog().notification("[B][COLOR red]| PLAY.TO |[/COLOR][/B]", f"TMDB : Chyba odpovědi API", xbmcgui.NOTIFICATION_ERROR, 3000)



def tmdb_toggle_watchlist(tmdb_id, media_type='movie', add=True):
    _toggle_tmdb_list('watchlist', tmdb_id, media_type, add)



def tmdb_toggle_favorite(tmdb_id, media_type='movie', add=True):
    _toggle_tmdb_list('favorite', tmdb_id, media_type, add)



def tmdb_remove_rating(tmdb_id, media_type='movie'):
    data = load_account_data()
    session_id = data.get('session_id')
    if not session_id:
        popinfo("TMDB : Nejsi přihlášen !", icon=xbmcgui.NOTIFICATION_ERROR)
        return

    url = f"{BASE_URL}/{media_type}/{tmdb_id}/rating"
    params = {'api_key': API_KEY, 'session_id': session_id}

    try:
        res = safe_post(SESSION, url, params=params, json={}, timeout=15)
        if res is None:
            raise requests.exceptions.RequestException('Network error')
        # use the response as-is; TMDB may accept DELETE via this session helper depending on API client
        res.raise_for_status()

        response_data = res.json()
        if response_data.get('success') or response_data.get('status_code') == 13:
            popinfo("TMDB : HODNOCENÍ ODSTRANĚNO", icon=xbmcgui.NOTIFICATION_INFO)
        else:
            raise ValueError(f"API nevrátilo úspěch: {response_data.get('status_message', 'Neznámá chyba')}")

    except requests.exceptions.RequestException as e:
        log(f"TMDB - Chyba API při odstraňování hodnocení: {e}", level=xbmc.LOGERROR)
        popinfo("TMDB : Chyba při odstraňování hodnocení", icon=xbmcgui.NOTIFICATION_ERROR)



def tmdb_rate_prompt_and_send(tmdb_id, media_type='movie'):
    kb = xbmc.Keyboard('', '·   ZADEJ  [ FUCKING ]  HODNOCENÍ  ( 0.5 – 10.0 )   ·')
    kb.doModal()
    # If invoked via router action, ensure directory is closed on cancel to avoid spinner
    if not kb.isConfirmed():
        try:
            xbmcplugin.endOfDirectory(0, succeeded=False)
        except Exception:
            pass
        return
    try:
        value = float(kb.getText().strip())
        if value < 0.5 or value > 10:
            raise ValueError
        data = load_account_data()
        session_id = data.get('session_id')
        if not session_id:
            xbmcgui.Dialog().notification("[B][COLOR red]| PLAY.TO |[/COLOR][/B]", "TMDB : Nejsi přihlášen !", xbmcgui.NOTIFICATION_ERROR, 3000)
            return

        url = f"{BASE_URL}/{media_type}/{tmdb_id}/rating"
        params = {'api_key': API_KEY, 'session_id': session_id}
        res = safe_post(SESSION, url, params=params, json={'value': value}, timeout=15)
        if res is not None and (res.status_code == 201 or res.status_code == 200):
            xbmcgui.Dialog().notification("[B][COLOR orange]| PLAY.TO |[/COLOR][/B]", f"TMDB : HODNOCENO  =  {value}/10", xbmcgui.NOTIFICATION_INFO, 3000)
        else:
            xbmcgui.Dialog().notification("[B][COLOR red]| PLAY.TO |[/COLOR][/B]", "TMDB : Chyba při hodnocení", xbmcgui.NOTIFICATION_ERROR, 3000)
    except ValueError:
        xbmcgui.Dialog().ok("[B][COLOR red]| PLAY.TO |[/COLOR][/B]", "TMDB : Neplatné číslo, hodnota musí být 0.5–10.0")
