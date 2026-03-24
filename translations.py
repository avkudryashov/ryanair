"""i18n translations for the web UI."""

SUPPORTED_LOCALES = {
    'en': 'English',
    'es': 'Español',
    'it': 'Italiano',
    'fr': 'Français',
    'pt': 'Português',
    'de': 'Deutsch',
    'ru': 'Русский',
}

DEFAULT_LOCALE = 'en'

TRANSLATIONS = {
    # ── Page title & meta ──
    'page_title': {
        'en': 'Ryanair FlyNomad — Cheap Flights & Multi-City Trip Planner',
        'es': 'Ryanair FlyNomad — Vuelos Baratos y Planificador Multi-Ciudad',
        'it': 'Ryanair FlyNomad — Voli Economici e Pianificatore Multi-Città',
        'fr': 'Ryanair FlyNomad — Vols Pas Chers et Planificateur Multi-Villes',
        'pt': 'Ryanair FlyNomad — Voos Baratos e Planejador Multi-Cidades',
        'de': 'Ryanair FlyNomad — Billigflüge & Multi-City-Reiseplaner',
        'ru': 'Ryanair FlyNomad — Дешёвые авиабилеты и планировщик маршрутов',
    },
    'meta_description': {
        'en': 'Find the cheapest flights and plan multi-city trips with flexible dates. Explore destinations or build round-trip routes through 1-4 cities.',
        'es': 'Encuentra los vuelos más baratos y planifica viajes multi-ciudad con fechas flexibles. Explora destinos o construye rutas de ida y vuelta por 1-4 ciudades.',
        'it': 'Trova i voli più economici e pianifica viaggi multi-città con date flessibili. Esplora destinazioni o crea percorsi di andata e ritorno attraverso 1-4 città.',
        'fr': 'Trouvez les vols les moins chers et planifiez des voyages multi-villes avec des dates flexibles. Explorez des destinations ou créez des itinéraires aller-retour à travers 1 à 4 villes.',
        'pt': 'Encontre os voos mais baratos e planeje viagens multi-cidades com datas flexíveis. Explore destinos ou crie rotas de ida e volta por 1-4 cidades.',
        'de': 'Finden Sie die günstigsten Flüge und planen Sie Multi-City-Reisen mit flexiblen Daten. Entdecken Sie Ziele oder erstellen Sie Hin- und Rückflugrouten durch 1-4 Städte.',
        'ru': 'Находите самые дешёвые авиабилеты и планируйте маршруты через 1-4 города с гибкими датами. Исследуйте направления или стройте маршруты с возвратом.',
    },
    'og_title': {
        'en': 'Ryanair FlyNomad — Cheap Flights & Multi-City Trip Planner',
        'es': 'Ryanair FlyNomad — Vuelos Baratos y Rutas Multi-Ciudad',
        'it': 'Ryanair FlyNomad — Voli Economici e Percorsi Multi-Città',
        'fr': 'Ryanair FlyNomad — Vols Pas Chers et Itinéraires Multi-Villes',
        'pt': 'Ryanair FlyNomad — Voos Baratos e Rotas Multi-Cidades',
        'de': 'Ryanair FlyNomad — Billigflüge & Multi-City-Routen',
        'ru': 'Ryanair FlyNomad — Дешёвые авиабилеты и маршруты',
    },
    'og_description': {
        'en': 'Find cheap flights and plan multi-city round trips with flexible dates.',
        'es': 'Encuentra vuelos baratos y planifica viajes multi-ciudad con fechas flexibles.',
        'it': 'Trova voli economici e pianifica viaggi multi-città con date flessibili.',
        'fr': 'Trouvez des vols pas chers et planifiez des voyages multi-villes avec des dates flexibles.',
        'pt': 'Encontre voos baratos e planeje viagens multi-cidades com datas flexíveis.',
        'de': 'Finden Sie günstige Flüge und planen Sie Multi-City-Reisen mit flexiblen Daten.',
        'ru': 'Находите дешёвые авиабилеты и планируйте маршруты через несколько городов.',
    },
    'jsonld_description': {
        'en': 'Find cheap flights and plan multi-city round trips with flexible dates',
        'es': 'Encuentra vuelos baratos y planifica viajes multi-ciudad con fechas flexibles',
        'it': 'Trova voli economici e pianifica viaggi multi-città con date flessibili',
        'fr': 'Trouvez des vols pas chers et planifiez des voyages multi-villes',
        'pt': 'Encontre voos baratos e planeje viagens multi-cidades com datas flexíveis',
        'de': 'Finden Sie günstige Flüge und planen Sie Multi-City-Reisen',
        'ru': 'Находите дешёвые авиабилеты и планируйте маршруты через несколько городов',
    },

    # ── Header ──
    'subtitle': {
        'en': 'Cheap flights & multi-city trip planner',
        'es': 'Vuelos baratos y planificador multi-ciudad',
        'it': 'Voli economici e pianificatore multi-città',
        'fr': 'Vols pas chers et planificateur multi-villes',
        'pt': 'Voos baratos e planejador multi-cidades',
        'de': 'Billigflüge & Multi-City-Reiseplaner',
        'ru': 'Дешёвые авиабилеты и планировщик маршрутов',
    },
    'skip_to_results': {
        'en': 'Skip to results',
        'es': 'Ir a resultados',
        'it': 'Vai ai risultati',
        'fr': 'Aller aux résultats',
        'pt': 'Ir para resultados',
        'de': 'Zu Ergebnissen springen',
        'ru': 'Перейти к результатам',
    },

    # ── Form labels ──
    'origin_airport': {
        'en': 'Departure airport',
        'es': 'Aeropuerto de salida',
        'it': 'Aeroporto di partenza',
        'fr': 'Aéroport de départ',
        'pt': 'Aeroporto de partida',
        'de': 'Abflughafen',
        'ru': 'Аэропорт вылета',
    },
    'departure_date': {
        'en': 'Departure date',
        'es': 'Fecha de salida',
        'it': 'Data di partenza',
        'fr': 'Date de départ',
        'pt': 'Data de partida',
        'de': 'Abflugdatum',
        'ru': 'Дата вылета',
    },
    'flex_days': {
        'en': '± days',
        'es': '± días',
        'it': '± giorni',
        'fr': '± jours',
        'pt': '± dias',
        'de': '± Tage',
        'ru': '± дней',
    },
    'nights': {
        'en': 'Nights',
        'es': 'Noches',
        'it': 'Notti',
        'fr': 'Nuits',
        'pt': 'Noites',
        'de': 'Nächte',
        'ru': 'Ночей',
    },
    'max_price': {
        'en': 'Max price',
        'es': 'Precio máx.',
        'it': 'Prezzo max.',
        'fr': 'Prix max.',
        'pt': 'Preço máx.',
        'de': 'Max. Preis',
        'ru': 'Макс. цена',
    },
    'search_btn': {
        'en': 'Search flights',
        'es': 'Buscar vuelos',
        'it': 'Cerca voli',
        'fr': 'Rechercher',
        'pt': 'Pesquisar voos',
        'de': 'Flüge suchen',
        'ru': 'Найти рейсы',
    },
    'exclude_countries': {
        'en': 'Exclude countries',
        'es': 'Excluir países',
        'it': 'Escludi paesi',
        'fr': 'Exclure pays',
        'pt': 'Excluir países',
        'de': 'Länder ausschließen',
        'ru': 'Исключить страны',
    },
    'exclude_airports': {
        'en': 'Exclude airports',
        'es': 'Excluir aeropuertos',
        'it': 'Escludi aeroporti',
        'fr': 'Exclure aéroports',
        'pt': 'Excluir aeroportos',
        'de': 'Flughäfen ausschließen',
        'ru': 'Исключить аэропорты',
    },
    'select_countries': {
        'en': 'Select countries…',
        'es': 'Seleccionar países…',
        'it': 'Seleziona paesi…',
        'fr': 'Sélectionner pays…',
        'pt': 'Selecionar países…',
        'de': 'Länder wählen…',
        'ru': 'Выберите страны…',
    },
    'select_airports': {
        'en': 'Select airports…',
        'es': 'Seleccionar aeropuertos…',
        'it': 'Seleziona aeroporti…',
        'fr': 'Sélectionner aéroports…',
        'pt': 'Selecionar aeroportos…',
        'de': 'Flughäfen wählen…',
        'ru': 'Выберите аэропорты…',
    },
    'search_placeholder': {
        'en': 'Search…',
        'es': 'Buscar…',
        'it': 'Cerca…',
        'fr': 'Rechercher…',
        'pt': 'Pesquisar…',
        'de': 'Suchen…',
        'ru': 'Поиск…',
    },
    'selected_count': {
        'en': 'Selected: {n}',
        'es': 'Seleccionados: {n}',
        'it': 'Selezionati: {n}',
        'fr': 'Sélectionnés : {n}',
        'pt': 'Selecionados: {n}',
        'de': 'Ausgewählt: {n}',
        'ru': 'Выбрано: {n}',
    },

    # ── Aria labels ──
    'prev_day': {
        'en': 'Previous day',
        'es': 'Día anterior',
        'it': 'Giorno precedente',
        'fr': 'Jour précédent',
        'pt': 'Dia anterior',
        'de': 'Vorheriger Tag',
        'ru': 'Предыдущий день',
    },
    'next_day': {
        'en': 'Next day',
        'es': 'Día siguiente',
        'it': 'Giorno successivo',
        'fr': 'Jour suivant',
        'pt': 'Próximo dia',
        'de': 'Nächster Tag',
        'ru': 'Следующий день',
    },
    'search_form': {
        'en': 'Search form',
        'es': 'Formulario de búsqueda',
        'it': 'Modulo di ricerca',
        'fr': 'Formulaire de recherche',
        'pt': 'Formulário de pesquisa',
        'de': 'Suchformular',
        'ru': 'Форма поиска',
    },
    'filter_countries': {
        'en': 'Filter countries',
        'es': 'Filtrar países',
        'it': 'Filtra paesi',
        'fr': 'Filtrer pays',
        'pt': 'Filtrar países',
        'de': 'Länder filtern',
        'ru': 'Фильтр стран',
    },
    'filter_airports': {
        'en': 'Filter airports',
        'es': 'Filtrar aeropuertos',
        'it': 'Filtra aeroporti',
        'fr': 'Filtrer aéroports',
        'pt': 'Filtrar aeroportos',
        'de': 'Flughäfen filtern',
        'ru': 'Фильтр аэропортов',
    },

    # ── Results ──
    'results_found': {
        'en': 'Found <strong>{n}</strong> {results_word}',
        'es': 'Encontrados <strong>{n}</strong> {results_word}',
        'it': 'Trovati <strong>{n}</strong> {results_word}',
        'fr': '<strong>{n}</strong> {results_word} trouvés',
        'pt': 'Encontrados <strong>{n}</strong> {results_word}',
        'de': '<strong>{n}</strong> {results_word} gefunden',
        'ru': 'Найдено <strong>{n}</strong> {results_word}',
    },
    'results_word': {
        'en': lambda n: 'result' if n == 1 else 'results',
        'es': lambda n: 'resultado' if n == 1 else 'resultados',
        'it': lambda n: 'risultato' if n == 1 else 'risultati',
        'fr': lambda n: 'résultat' if n == 1 else 'résultats',
        'pt': lambda n: 'resultado' if n == 1 else 'resultados',
        'de': lambda n: 'Ergebnis' if n == 1 else 'Ergebnisse',
        'ru': lambda n: 'вариант' if n == 1 else ('варианта' if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else 'вариантов'),
    },
    'nights_word': {
        'en': lambda n: 'night' if n == 1 else 'nights',
        'es': lambda n: 'noche' if n == 1 else 'noches',
        'it': lambda n: 'notte' if n == 1 else 'notti',
        'fr': lambda n: 'nuit' if n == 1 else 'nuits',
        'pt': lambda n: 'noite' if n == 1 else 'noites',
        'de': lambda n: 'Nacht' if n == 1 else 'Nächte',
        'ru': lambda n: 'ночь' if n % 10 == 1 and n % 100 != 11 else ('ночи' if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else 'ночей'),
    },
    'hours_short': {
        'en': 'h',
        'es': 'h',
        'it': 'h',
        'fr': 'h',
        'pt': 'h',
        'de': 'h',
        'ru': 'ч',
    },
    'min_ago': {
        'en': '{n} min ago',
        'es': 'hace {n} min',
        'it': '{n} min fa',
        'fr': 'il y a {n} min',
        'pt': 'há {n} min',
        'de': 'vor {n} Min.',
        'ru': '{n} мин назад',
    },
    'prices_fresh': {
        'en': 'live prices',
        'es': 'precios actuales',
        'it': 'prezzi attuali',
        'fr': 'prix en direct',
        'pt': 'preços atuais',
        'de': 'aktuelle Preise',
        'ru': 'актуальные цены',
    },
    'api_unavailable': {
        'en': 'API unavailable, cached data',
        'es': 'API no disponible, datos en caché',
        'it': 'API non disponibile, dati dalla cache',
        'fr': 'API indisponible, données en cache',
        'pt': 'API indisponível, dados em cache',
        'de': 'API nicht verfügbar, zwischengespeicherte Daten',
        'ru': 'API недоступен, данные из кэша',
    },
    'search_results': {
        'en': 'Search results',
        'es': 'Resultados de búsqueda',
        'it': 'Risultati della ricerca',
        'fr': 'Résultats de recherche',
        'pt': 'Resultados da pesquisa',
        'de': 'Suchergebnisse',
        'ru': 'Результаты поиска',
    },

    # ── Table headers ──
    'th_destination': {
        'en': 'Destination',
        'es': 'Destino',
        'it': 'Destinazione',
        'fr': 'Destination',
        'pt': 'Destino',
        'de': 'Ziel',
        'ru': 'Направление',
    },
    'th_price': {
        'en': 'Price',
        'es': 'Precio',
        'it': 'Prezzo',
        'fr': 'Prix',
        'pt': 'Preço',
        'de': 'Preis',
        'ru': 'Цена',
    },
    'th_outbound': {
        'en': 'Outbound',
        'es': 'Ida',
        'it': 'Andata',
        'fr': 'Aller',
        'pt': 'Ida',
        'de': 'Hinflug',
        'ru': 'Туда',
    },
    'th_return': {
        'en': 'Return',
        'es': 'Vuelta',
        'it': 'Ritorno',
        'fr': 'Retour',
        'pt': 'Volta',
        'de': 'Rückflug',
        'ru': 'Обратно',
    },
    'th_nights': {
        'en': 'Nights',
        'es': 'Noches',
        'it': 'Notti',
        'fr': 'Nuits',
        'pt': 'Noites',
        'de': 'Nächte',
        'ru': 'Ночей',
    },
    'th_hours': {
        'en': 'Hours',
        'es': 'Horas',
        'it': 'Ore',
        'fr': 'Heures',
        'pt': 'Horas',
        'de': 'Stunden',
        'ru': 'Часов',
    },

    # ── Empty / error states ──
    'no_results': {
        'en': 'No matching flights found',
        'es': 'No se encontraron vuelos',
        'it': 'Nessun volo trovato',
        'fr': 'Aucun vol trouvé',
        'pt': 'Nenhum voo encontrado',
        'de': 'Keine passenden Flüge gefunden',
        'ru': 'Подходящих рейсов не найдено',
    },
    'try_change_dates': {
        'en': 'Try changing dates or increasing your budget',
        'es': 'Intenta cambiar las fechas o aumentar el presupuesto',
        'it': 'Prova a cambiare le date o ad aumentare il budget',
        'fr': 'Essayez de changer les dates ou d\'augmenter le budget',
        'pt': 'Tente alterar as datas ou aumentar o orçamento',
        'de': 'Versuchen Sie andere Daten oder ein höheres Budget',
        'ru': 'Попробуйте изменить даты или увеличить бюджет',
    },
    'error_missing_fields': {
        'en': 'Please enter departure date and number of nights',
        'es': 'Indique la fecha de salida y el número de noches',
        'it': 'Inserisci la data di partenza e il numero di notti',
        'fr': 'Veuillez indiquer la date de départ et le nombre de nuits',
        'pt': 'Indique a data de partida e o número de noites',
        'de': 'Bitte Abflugdatum und Anzahl der Nächte angeben',
        'ru': 'Укажите дату вылета и количество ночей',
    },
    'error_bad_format': {
        'en': 'Invalid format. Date: YYYY-MM-DD, nights: 1,2,3',
        'es': 'Formato inválido. Fecha: YYYY-MM-DD, noches: 1,2,3',
        'it': 'Formato non valido. Data: YYYY-MM-DD, notti: 1,2,3',
        'fr': 'Format invalide. Date : YYYY-MM-DD, nuits : 1,2,3',
        'pt': 'Formato inválido. Data: YYYY-MM-DD, noites: 1,2,3',
        'de': 'Ungültiges Format. Datum: YYYY-MM-DD, Nächte: 1,2,3',
        'ru': 'Неверный формат данных. Дата: YYYY-MM-DD, ночи: 1,2,3',
    },
    'error_search': {
        'en': 'Search error: {e}',
        'es': 'Error de búsqueda: {e}',
        'it': 'Errore di ricerca: {e}',
        'fr': 'Erreur de recherche : {e}',
        'pt': 'Erro na pesquisa: {e}',
        'de': 'Suchfehler: {e}',
        'ru': 'Ошибка поиска: {e}',
    },

    # ── Destination selector & flow view ──
    'destination_airport': {
        'en': 'Destination',
        'es': 'Destino',
        'it': 'Destinazione',
        'fr': 'Destination',
        'pt': 'Destino',
        'de': 'Ziel',
        'ru': 'Направление',
    },
    'all_destinations': {
        'en': 'All destinations',
        'es': 'Todos los destinos',
        'it': 'Tutte le destinazioni',
        'fr': 'Toutes les destinations',
        'pt': 'Todos os destinos',
        'de': 'Alle Ziele',
        'ru': 'Все направления',
    },
    'loading_destinations': {
        'en': 'Loading destinations...',
        'es': 'Cargando destinos...',
        'it': 'Caricamento destinazioni...',
        'fr': 'Chargement des destinations...',
        'pt': 'Carregando destinos...',
        'de': 'Ziele werden geladen...',
        'ru': 'Загрузка направлений...',
    },
    'total_price': {
        'en': 'Total',
        'es': 'Total',
        'it': 'Totale',
        'fr': 'Total',
        'pt': 'Total',
        'de': 'Gesamt',
        'ru': 'Итого',
    },
    'view_flow': {
        'en': 'Flow',
        'es': 'Flujo',
        'it': 'Flusso',
        'fr': 'Flux',
        'pt': 'Fluxo',
        'de': 'Flow',
        'ru': 'Маршрут',
    },
    'view_table': {
        'en': 'Table',
        'es': 'Tabla',
        'it': 'Tabella',
        'fr': 'Tableau',
        'pt': 'Tabela',
        'de': 'Tabelle',
        'ru': 'Таблица',
    },

    # ── Nomad mode ──
    'nomad_tab': {
        'en': 'Nomad Mode',
        'es': 'Modo Nómada',
        'it': 'Modalità Nomade',
        'fr': 'Mode Nomade',
        'pt': 'Modo Nômade',
        'de': 'Nomaden-Modus',
        'ru': 'Режим Nomad',
    },
    'nomad_nights_label': {
        'en': 'Nights per city',
        'es': 'Noches por ciudad',
        'it': 'Notti per città',
        'fr': 'Nuits par ville',
        'pt': 'Noites por cidade',
        'de': 'Nächte pro Stadt',
        'ru': 'Ночей в городе',
    },
    'nomad_hops_label': {
        'en': 'Cities',
        'es': 'Ciudades',
        'it': 'Città',
        'fr': 'Villes',
        'pt': 'Cidades',
        'de': 'Städte',
        'ru': 'Городов',
    },
    'nomad_topn_label': {
        'en': 'Results',
        'es': 'Resultados',
        'it': 'Risultati',
        'fr': 'Résultats',
        'pt': 'Resultados',
        'de': 'Ergebnisse',
        'ru': 'Вариантов',
    },
    'nomad_start_btn': {
        'en': 'Search routes',
        'es': 'Buscar rutas',
        'it': 'Cerca percorsi',
        'fr': 'Rechercher itinéraires',
        'pt': 'Pesquisar rotas',
        'de': 'Routen suchen',
        'ru': 'Найти маршруты',
    },
    'nomad_searching': {
        'en': 'Searching routes... This may take up to a minute.',
        'es': 'Buscando rutas... Esto puede tardar hasta un minuto.',
        'it': 'Ricerca percorsi... Potrebbe richiedere fino a un minuto.',
        'fr': 'Recherche d\'itinéraires... Cela peut prendre jusqu\'à une minute.',
        'pt': 'Pesquisando rotas... Isso pode levar até um minuto.',
        'de': 'Routen werden gesucht... Dies kann bis zu einer Minute dauern.',
        'ru': 'Поиск маршрутов... Это может занять до минуты.',
    },
    'nomad_no_routes': {
        'en': 'No routes found. Try increasing the budget or reducing the number of cities.',
        'es': 'No se encontraron rutas. Intente aumentar el presupuesto o reducir el número de ciudades.',
        'it': 'Nessun percorso trovato. Prova ad aumentare il budget o a ridurre il numero di città.',
        'fr': 'Aucun itinéraire trouvé. Essayez d\'augmenter le budget ou de réduire le nombre de villes.',
        'pt': 'Nenhuma rota encontrada. Tente aumentar o orçamento ou reduzir o número de cidades.',
        'de': 'Keine Routen gefunden. Versuchen Sie, das Budget zu erhöhen oder die Anzahl der Städte zu reduzieren.',
        'ru': 'Маршруты не найдены. Попробуйте увеличить бюджет или уменьшить число городов.',
    },
    'nomad_routes_found': {
        'en': 'Found {n} routes',
        'es': '{n} rutas encontradas',
        'it': '{n} percorsi trovati',
        'fr': '{n} itinéraires trouvés',
        'pt': '{n} rotas encontradas',
        'de': '{n} Routen gefunden',
        'ru': 'Найдено {n} маршрутов',
    },
    'nomad_stay': {
        'en': lambda n: f'{n} night' + ('s' if n != 1 else ''),
        'es': lambda n: f'{n} noche' + ('s' if n != 1 else ''),
        'it': lambda n: f'{n} nott' + ('e' if n == 1 else 'i'),
        'fr': lambda n: f'{n} nuit' + ('s' if n != 1 else ''),
        'pt': lambda n: f'{n} noite' + ('s' if n != 1 else ''),
        'de': lambda n: f'{n} Nacht' if n == 1 else f'{n} Nächte',
        'ru': lambda n: f'{n} ' + ('ночь' if n == 1 else ('ночи' if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else 'ночей')),
    },

    # ── Footer ──
    'footer_text': {
        'en': 'Data provided by Ryanair API. Prices may differ at the time of booking.',
        'es': 'Datos proporcionados por la API de Ryanair. Los precios pueden variar al momento de la reserva.',
        'it': 'Dati forniti dall\'API Ryanair. I prezzi possono variare al momento della prenotazione.',
        'fr': 'Données fournies par l\'API Ryanair. Les prix peuvent varier au moment de la réservation.',
        'pt': 'Dados fornecidos pela API da Ryanair. Os preços podem variar no momento da reserva.',
        'de': 'Daten von der Ryanair-API. Preise können zum Zeitpunkt der Buchung abweichen.',
        'ru': 'Данные предоставлены Ryanair API. Цены могут отличаться на момент бронирования.',
    },
}

# OG locale mapping
OG_LOCALES = {
    'en': 'en_US', 'es': 'es_ES', 'it': 'it_IT',
    'fr': 'fr_FR', 'pt': 'pt_PT', 'de': 'de_DE', 'ru': 'ru_RU',
}


def get_translator(lang):
    """Returns a translation function for the given locale."""
    if lang not in SUPPORTED_LOCALES:
        lang = DEFAULT_LOCALE

    def _(key, **kwargs):
        entry = TRANSLATIONS.get(key, {})
        text = entry.get(lang, entry.get(DEFAULT_LOCALE, key))
        if callable(text):
            return text(**kwargs) if kwargs else text
        if kwargs:
            return text.format(**kwargs)
        return text

    return _


def detect_locale(request):
    """Detect locale from ?lang= param or Accept-Language header."""
    # 1. Explicit ?lang= parameter
    lang = request.args.get('lang', '').strip().lower()
    if lang in SUPPORTED_LOCALES:
        return lang

    # 2. Accept-Language header
    accept = request.headers.get('Accept-Language', '')
    for part in accept.split(','):
        code = part.split(';')[0].strip().lower()
        # Try exact match first (e.g. "pt-br" → "pt")
        short = code[:2]
        if short in SUPPORTED_LOCALES:
            return short

    return DEFAULT_LOCALE
