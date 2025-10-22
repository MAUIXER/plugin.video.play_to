# KODI 22 PIERS : VIDEO ADDON


    # ============================================================================================= # 
    # == # ========================     X B M C  --  K O D I    2 2    P I E R S    ========== # == # 
    #    #                                                                                     #    # 
    #    #         _____ ____  __  __________  __      __________  ____  __ __                 #    # 
    #    #        / ___// __ \/ / / /_  __/ / / /     / ____/ __ \/ __ \/ //_/                 #    # 
    #    #        \__ \/ / / / / / / / / / /_/ /_____/ /_  / / / / /_/ / ,<                    #    # 
    #    #       ___/ / /_/ / /_/ / / / / __  /_____/ __/ / /_/ / _, _/ /| |                   #    # 
    #    #      /____/\_______________ /_/ /_/  ______  ___________|_/_/ |_|                   #    # 
    #    #         / | / / ____/_  __/ | |     / / __ \/ __ \/ //_/                            #    # 
    #    #        /  |/ / __/   / /____| | /| / / / / / /_/ / ,<                               #    # 
    #    #       / /|  / /___  / /_____/ |/ |/ / /_/ / _, _/ /| |                              #    # 
    #    #      /_/ |_/_____/ /_/      |__/|__/\____/_/ |_/_/ |_|   (TM) 2025 Mau!X ER . . .   #    # 
    #    #                                                                                     #    # 
    #    #                                                                                     #    # 
    # == # =================================================================================== # == # 
    # =============    [  P L U G I N . V I D E O . P L A Y _ T O  ]    =========================== # 


## 1. Abstrakt


`plugin.video.play_to` je doplněk pro multimediální centrum Kodi, který slouží 
jako klient pro streamovací službu Prehraj.to. Jeho primárním architektonickým 
cílem je zajištění **stavové konzistence a maximální obohacení metadat** před 
jejich předáním přehrávači Kodi. Tím je dosaženo spolehlivé integrace s interními 
mechanismy Kodi a externími službami pro sledování obsahu, jako je TRAKT.TV ...


Doplněk je napsán v Pythonu a využívá Kodi API (`xbmc`, `xbmcgui`, `xbmcplugin`).

---

## 2. Architektura a princip fungování


### 2.1. Základní filozofie: "Metadata-First"

Na rozdíl od jednodušších doplňků, které pouze najdou přehrávatelný odkaz a předají
ho Kodi, je tento doplněk postaven na principu **"Metadata-First"**. Jeho hlavním 
úkolem není pouze přehrát video, ale předat finální funkci `xbmcplugin.setResolvedUrl()` 
plně zkonstruovaný a metadaty obohacený objekt `xbmcgui.ListItem`. Tento objekt musí 
obsahovat veškeré dostupné informace (název, rok, popis, žánry, hodnocení, obrázky,
TMDB ID), aby přehrávač Kodi přesně věděl, co přehrává.


### 2.2. Řízení běhu: Router


Vstupním bodem doplňku je `main.py`, který okamžitě předává řízení funkci `plugin.router()`. 
Tato funkce funguje jako stavový automat, který na základě parametru `action` v URL 
pluginu (`plugin://...`) rozhoduje, která část logiky se má provést. Každá akce uživatele
(kliknutí na kategorii, spuštění hledání, přehrání videa) generuje nové volání doplňku 
s jiným `action` parametrem.


### 2.3. Pracovní postupy získávání metadat


Doplněk implementuje dva hlavní pracovní postupy pro zajištění maximální kvality metadat:


#### A) Postup řízený metadaty (Procházení TMDB/ČSFD)


Tento postup se používá, když uživatel začíná v katalogu, kde jsou data již známá a čistá.

1.  **Výběr položky**: Uživatel si v přehledné knihovně (např. "Trendy filmy") vybere položku.
V tomto okamžiku má doplněk k dispozici přesné TMDB ID, název, rok a další data. Tato data 
jsou serializována (typicky do JSON) a uložena jako `meta` parametr v URL další akce.

2.  **Hledání zdrojů (`find_sources`)**: Po kliknutí se spustí akce, která vezme čistá metadata
a použije je ke konstrukci vyhledávacího dotazu pro Prehraj.to. Využívá k tomu interní 
volání `search(query, return_results=True)`.

3.  **Zobrazení streamů**: Uživatel vidí seznam nalezených streamů. Každá položka v tomto 
seznamu si s sebou stále nese původní, kompletní `meta` balíček.

4.  **Přehrání (`resolve_video`)**: Po kliknutí na stream se spustí finální akce `play`, 
která funkci `resolve_video` předá jak odkaz na stream, tak kompletní `meta` balíček. `resolve_video` poté sestaví finální `ListItem` a předá ho Kodi.


#### B) Postup řízený dotazem (Přímé hledání / Sledované)


Tento postup se používá, když na vstupu máme pouze nestrukturovaný textový řetězec 
(dotaz od uživatele nebo nepřesný název z webu).


1.  **Získání dotazu**: Uživatel zadá text do vyhledávání, nebo doplněk získá "špinavý" název ze sekce "Sledované".
2.  **Normalizace a parsování (`clean_title_for_tmdb`)**: Tento klíčový modul vezme vstupní řetězec a provede několik operací:

    -   Detekuje, zda se jedná o seriál          ( dle formátu `SxxExx` )
    -   Pomocí regexu extrahuje rok vydání       ( `\b(19|20)\d{2}\b` )
    -   Odstraní veškerý balast a klíčová slova  ( `CZ Dabing`, `1080p`, `4K`, `WEB-DL` )
    -   Normalizuje interpunkci a mezery
    -   Výstupem je čistý název a rok
    
3.  **Získání metadat z TMDB**: Doplněk použije vyčištěný název a rok k dotazu na endpoint `/search/multi` v TMDB API. 
4.  **Pokud je nalezen **: Jeden přesný výsledek (nebo ho uživatel vybere z dialogu), doplněk si z něj sestaví definitivní `meta` balíček.
5.  **Hledání streamů (`search`)**: Nyní se s původním dotazem prohledá Prehraj.to a zobrazí se seznam streamů.
6.  **Přehrání (`resolve_video`)**: Při výběru streamu se použije `meta` balíček získaný v kroku 3. Tím je zajištěno, že i nepřesné zdroje vedou k přesným metadatům v přehrávači.

---


## 3. Detailní popis komponent a funkcí (`plugin.py`)


### 3.1. Hlavní logické funkce


-   `router(paramstring)`: Srdce doplňku. Parsuje URL, identifikuje parametr `action` a volá příslušnou funkci pro obsluhu.
-   `menu()`: Generuje položky hlavní obrazovky doplňku.


### 3.2. Zpracování metadat a streamů

-   `clean_title_for_tmdb(title)`: Centrální normalizační funkce. Přijímá textový řetězec a vrací `(clean_title, year)`. Její robustnost je klíčová pro úspěšnost metadat u nepřesných zdrojů.
-   `search(name, return_results=False)`: Duální funkce.
    -   `return_results=False`: Interaktivní režim pro uživatele. Zobrazí klávesnici, provede celý "Postup řízený dotazem" (čištění, TMDB, Prehraj.to) a zobrazí výsledky.
    -   `return_results=True`: Interní režim. Funguje jako "hloupý" scraper, který pouze vrátí seznam výsledků z Prehraj.to. Využívá ho funkce `find_sources`.
-   `find_sources(meta_json)`: Most mezi TMDB katalogem a seznamem streamů. Vezme přesná `meta` data, zavolá `search(..., return_results=True)` a zobrazí výsledky, přičemž ke každému připojí původní `meta` data.
-   `find_meta_and_resolve(title, link)`: Specializovaná funkce pro sekci "Sledované". Spojuje logiku `clean_title_for_tmdb` a `resolve_video` do jednoho kroku pro okamžité přehrání po kliknutí.
-   `resolve_video(link, cookies, meta_json)`: Finální fáze přehrávání. Jejím jediným úkolem je:
    1.  Získat přímý, přehrávatelný stream URL (např. `.mp4`).
    2.  Deserializovat `meta_json`.
    3.  Vytvořit `xbmcgui.ListItem`.
    4.  Naplnit jeho `infoTag` a `art` z `meta` dat.
    5.  Zavolat `xbmcplugin.setResolvedUrl()`.


### 3.3. Interakce s API a webem


-   `tmdb_fetch(endpoint, params)`: Centralizovaný wrapper pro všechny dotazy na TMDB API. Automaticky doplňuje `api_key` a `language` a stará se o zpracování HTTP požadavku.
-   `get_link(html_content)`: Parser pro HTML stránku konkrétního videa na Prehraj.to. Pomocí `BeautifulSoup` a `regex` hledá v JavaScriptu proměnné obsahující odkazy na video stream a titulky.
-   `get_premium()`: Stará se o přihlášení a správu session (cookies) pro prémiové uživatele.


### 3.4. Generování UI seznamů


-   `tmdb_list_items(data, ...)`: Klíčová funkce pro zobrazení jakéhokoliv seznamu z TMDB (trendy, žánry atd.). Iteruje přes `results` z TMDB odpovědi, pro každou položku vytváří `ListItem` a připravuje `meta` balíček pro další akci.
-   `most_watched()`, `history()`, `list_csfd_daily_tips()`: Funkce generující specifické seznamy pro dané sekce.

---


## 4. Detailní popis interakce s TMDB API


Komunikace s TMDB je plně zapouzdřena ve funkci `tmdb_fetch`.

-   **Princip**: Každá funkce, která potřebuje data z TMDB (např. `search`, `tmdb_trending`), si připraví název endpointu (např. `/search/multi`) a slovník s parametry (např. `{'query': 'Inception', 'year': '2010'}`).
-   **Wrapper `tmdb_fetch`**: Tato funkce převezme endpoint a parametry, přidá k nim povinné parametry `api_key` a `language` (z nastavení doplňku) a sestaví finální URL dotazu.
-   **Zpracování odpovědi**: Po odeslání GET požadavku je očekávána odpověď ve formátu JSON. `tmdb_fetch` tuto odpověď deserializuje na Python slovník a vrátí ho volající funkci. Zpracování chyb (např. HTTP 404 nebo 401) je také řešeno zde.
-   **Využívané endpointy**:
    -   `/search/multi`: Pro obecné vyhledávání filmů i seriálů.
    -   `/trending/{media_type}/week`: Pro sekci "Trendy".
    -   `/discover/{media_type}`: Pro sekci "Discover" a filtrování podle žánrů/roku.
    -   `/genre/{media_type}/list`: Pro získání seznamu všech dostupných žánrů.
    -   `/{media_type}/top_rated`: Pro nejlépe hodnocené.
    -   `/tv/{tv_id}/season/{season_number}`: Pro získání detailů o epizodách v sezóně.

---


## 5. Ladění (Debugging)


Pro ladění funkčnosti, zejména správnosti parsování názvů, jsou v kódu implementovány logovací zprávy. V Kodi logu (dostupném např. přes doplněk Log Viewer) hledejte řádky začínající:

-   `PLAY.TO CLEANER DEBUG:`: Ukazuje vstup a výstup centrální čistící funkce.
-   `PLAY.TO SEARCH DEBUG:`: Ukazuje, s jakým názvem a rokem se funkce `search` dotazuje TMDB.
-   `PLAY.TO CSFD DEBUG:`: Ukazuje, jaký dotaz je sestaven ze sekce ČSFD.
