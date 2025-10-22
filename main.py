# -*- coding: utf-8 -*-

import sys, xbmc, traceback

try: from resources.lib import plugin
except Exception as e:
    xbmc.log(f"| PLAY.TO MAIN - KRITICKÁ CHYBA : {e}\n{traceback.format_exc()}", level=xbmc.LOGERROR)
    sys.exit(1)

if __name__ == "__main__":
    params_str = sys.argv[2][1:] if len(sys.argv) > 2 else ""
    try: plugin.router(params_str)
    except Exception as e:
        xbmc.log(f"| PLAY.TO MAIN - FATÁLNÍ CHYBA V ROUTERU : {e}\n{traceback.format_exc()}", level=xbmc.LOGERROR)

