# -*- coding: utf-8 -*-


# =========================================================================
#
#  Module: files
#  Author: Mau!X ER
#  Created on: 20.10.2025
#  License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
# =========================================================================



import xbmc
import xbmcvfs

import os
import traceback


from resources.lib.utils import log, popinfo


try:
    import xbmcgui
    _xbmcgui_available = True
except ImportError:
    _xbmcgui_available = False





# =======================     F I L E S  :  DIRECTORY     =============================================================== #
# ======================================================================================================================= #


def ensure_dir(path):

    """
    FILES :: CREATE DIRECTORY
    -- Safely creates a directory using Kodi VFS, with OS fallback.
    -- Logs detailed errors if both methods fail.
    -- Does nothing if it already exists.
    -- Returns True if directory exists or was created, False otherwise.
    """

    if not path:
        log("FILES - WARNING : Attempted to ensure_dir with empty path", xbmc.LOGWARNING)
        return False

    vfs_exists = xbmcvfs.exists(path)
    if vfs_exists:
        # log(f"FILES - Directory already exists (VFS check) : {path}", xbmc.LOGDEBUG)
        return True

    vfs_success = False
    os_success = False
    vfs_error = None
    os_error = None

    try:
        if xbmcvfs.mkdirs(path):
            log(f"FILES - Created missing folder via VFS : {path}", xbmc.LOGINFO)
            vfs_success = True
        else:
            vfs_error = RuntimeError(f"VFS mkdirs returned false for {path}")
    except Exception as e_vfs:
        vfs_error = e_vfs

    if not vfs_success:
        try:
            local_path = xbmcvfs.translatePath(path)
            if local_path:
                 os.makedirs(local_path, exist_ok=True)
                 if os.path.exists(local_path):
                     log(f"FILES - Created missing folder via OS : {local_path}", xbmc.LOGINFO)
                     os_success = True
                 else:
                     os_error = RuntimeError("os.makedirs succeeded but path still doesn't exist")
            else:
                 os_error = ValueError("Translated path is empty")
        except Exception as e_os:
            os_error = e_os

    if not vfs_success and not os_success:
        log(f"FILES - FAILED to create folder : {path} -> VFS Error : {vfs_error} / OS Error : {os_error}\n{traceback.format_exc()}", xbmc.LOGERROR)
        return False

    return True


# =======================     F I L E S  :  FILES     =================================================================== #
# ======================================================================================================================= #


def ensure_file(path):

    """
    FILES :: CREATE FILES
    -- Safely creates a file if it doesn't exist.
    -- Returns True if file exists or was created, False otherwise.
    """

    if not path:
        log("FILES - WARNING : Attempted to ensure_file with empty path", xbmc.LOGWARNING)
        return False

    if xbmcvfs.exists(path):
        return True

    file_created = False
    parent_dir = os.path.dirname(path)

    if not parent_dir or not ensure_dir(parent_dir):
        log(f"FILES - Cannot create file because parent directory failed : {parent_dir}", xbmc.LOGERROR)
        return False

    try:
        handle = xbmcvfs.File(path, 'w')
        handle.close()
        log(f"FILES - Created missing file via VFS : {path}", xbmc.LOGINFO)
        file_created = True
        return True
        
    except Exception as e_vfs:
        log(f"FILES - VFS FAILED to create file : {path} -> {e_vfs}\n{traceback.format_exc()}", xbmc.LOGWARNING)

        try:
            local_path = xbmcvfs.translatePath(path)
            if local_path:
                open(local_path, 'a').close() 
                log(f"FILES - Created missing file via OS : {local_path}", xbmc.LOGINFO)
                file_created = True
        except Exception as e_os:
            log(f"FILES - FAILED to create file : {path} -> {e_os}\n{traceback.format_exc()}", xbmc.LOGERROR)

    return file_created


# =======================     F I L E S  :  DEFAULT DIRECTORIES     ===================================================== #
# ======================================================================================================================= #


def create_default_dirs(addon, profile, extra_dirs=None):

    """
    FILES :: CREATE DEFAULT DIRECTORIES
    -- Ensures standard plugin folders and essential files exist.
    """

    log(f"FILES - Running create_default_dirs. Profile path received : {profile}", xbmc.LOGINFO)

    if not ensure_dir(profile):
        log(f"FILES - ERROR : Failed to ensure profile directory exists : {profile}", xbmc.LOGERROR)
        if _xbmcgui_available:
            xbmcgui.Dialog().notification('[B][COLOR red] PLAY.TO [/COLOR][/B]', f'FILES : Selhalo vytvoření profilu : {profile}', xbmcgui.NOTIFICATION_ERROR, 7000)
        return


    ##########################################################################

    paths_from_settings = {
        'shared_cache_path': "special://userdata/PLAY-CACHE/CACHE-SHARED/",
        'ip_cache_dir': "special://userdata/PLAY-CACHE/CACHE-IP/",
        'playback_dir': "special://userdata/PLAY-CACHE/PLAYBACK/",
        'history_dir': "special://userdata/PLAY-CACHE/HISTORY/"
    }

    ##########################################################################


    dirs_to_ensure = []
    file_paths = {}

    for setting_id, default_path in paths_from_settings.items():
        try:
            setting_value = addon.getSetting(setting_id)
            path_to_translate = setting_value.strip() if setting_value else default_path
            translated_path = xbmcvfs.translatePath(path_to_translate)

            if translated_path:
                dir_path = translated_path
                if dir_path not in dirs_to_ensure:
                    dirs_to_ensure.append(dir_path)

                if setting_id == 'ip_cache_dir':
                    file_paths['ip_cache'] = os.path.join(dir_path, 'IP.CACHE')
                elif setting_id == 'playback_dir':
                    file_paths['playback'] = os.path.join(dir_path, 'PLAYBACK.JSON')
                elif setting_id == 'history_dir':
                    file_paths['history'] = os.path.join(dir_path, 'HISTORY.TXT')

            else:
                 log(f"FILES - WARNING : Could not translate path for setting '{setting_id}': '{path_to_translate}'", xbmc.LOGWARNING)
        except Exception as e_setting:
             log(f"FILES - Error processing setting '{setting_id}': {e_setting}", xbmc.LOGERROR)

    if extra_dirs and isinstance(extra_dirs, list):
        for d in extra_dirs:
            try:
                translated_extra = xbmcvfs.translatePath(d)
                if translated_extra and translated_extra not in dirs_to_ensure:
                    dirs_to_ensure.append(translated_extra)
            except Exception as e_extra:
                 log(f"FILES - Error translating extra_dir '{d}': {e_extra}", xbmc.LOGERROR)

    log(f"FILES - Ensuring directories exist : {dirs_to_ensure}", xbmc.LOGINFO)
    all_dirs_ok = True
    for d in dirs_to_ensure:
        if not ensure_dir(d):
            all_dirs_ok = False

    log(f"FILES - Ensuring essential files exist : {file_paths.values()}", xbmc.LOGINFO)
    all_files_ok = True

    if file_paths.get('ip_cache') and not ensure_file(file_paths['ip_cache']): all_files_ok = False
    if file_paths.get('playback') and not ensure_file(file_paths['playback']): all_files_ok = False
    if file_paths.get('history') and not ensure_file(file_paths['history']): all_files_ok = False

    if not all_dirs_ok or not all_files_ok:
         log("FILES - ERROR : Failed to ensure one or more directories / files", xbmc.LOGERROR)
         if _xbmcgui_available:
             xbmcgui.Dialog().notification('[B][COLOR red]| PLAY.TO |[/COLOR][/B]', 'FILES : Chyba při přípravě cache / souborů', xbmcgui.NOTIFICATION_ERROR, 5000)
