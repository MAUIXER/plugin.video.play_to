# -*- coding: utf-8 -*-


# =========================================================================
#
#  Module: speedtest
#  Author: Mau!X ER
#  Created on: 20.10.2025
#  License: AGPL v.3 https://www.gnu.org/licenses/agpl-3.0.html
#
# =========================================================================



import xbmcgui
import time
import requests

from resources.lib.utils import log, popinfo



##############################################################
DOWNLOAD_URL = "https://prg.download.datapacket.com/100mb.bin"
##############################################################



def diagnose_speed(addon):

    """
    SPEEDTEST :: TEST DOWNLOAD SPEED
    -- Testing download speed from  ( DOWNLOAD_URL )
    """

    dialog = xbmcgui.Dialog()
    dialog.notification(
        addon.getAddonInfo('name'),
        "[B][COLOR orange][ SPEEDTEST ][/COLOR][/B] - STAHUJI [B][COLOR limegreen]100 MB[/COLOR][/B]",
        xbmcgui.NOTIFICATION_INFO,
        10000
    )

    try:
        start = time.time()
        r = requests.get(DOWNLOAD_URL, stream=True, timeout=120)
        downloaded = 0

        for chunk in r.iter_content(chunk_size=1024 * 64):
            if chunk:
                downloaded += len(chunk)

        duration = time.time() - start

        # --- SPEEDTEST : Přepočet na megabity za sekundu  ( Mb/s )

        bits_downloaded = downloaded * 8
        mbps_download = (bits_downloaded / (1024 * 1024)) / duration if duration > 0 else 0

        dialog.notification(
            addon.getAddonInfo('name'),
            f"[B][COLOR orange][ SPEEDTEST ][/COLOR][/B] - RYCHLOST : [B][COLOR limegreen]{mbps_download:.2f} Mbps[/COLOR][/B]",
            xbmcgui.NOTIFICATION_INFO,
            20000
        )

    except Exception as e:
        dialog.notification(
            addon.getAddonInfo('name'),
            f"[B][COLOR red][ SPEEDTEST ][/COLOR][/B] - CHYBA STAHOVÁNÍ : {str(e)}",
            xbmcgui.NOTIFICATION_ERROR,
            10000
        )

