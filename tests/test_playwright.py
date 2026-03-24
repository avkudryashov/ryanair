"""Playwright E2E тесты для UI."""
import pytest
import threading
import time
from datetime import datetime
from unittest.mock import patch, MagicMock

# Запускаем Flask в отдельном потоке для тестов
_server_started = threading.Event()


@pytest.fixture(scope="module")
def flask_server():
    """Запускает Flask-сервер на localhost:5099 для Playwright тестов."""
    with patch('app.searcher') as mock_searcher:
        mock_searcher.get_airports.return_value = [
            {'code': 'VLC', 'name': 'Valencia', 'city': 'Valencia',
             'country': 'Spain', 'country_code': 'es', 'schengen': True,
             'lat': 39.489, 'lng': -0.481},
            {'code': 'BGY', 'name': 'Milan Bergamo', 'city': 'Bergamo',
             'country': 'Italy', 'country_code': 'it', 'schengen': True,
             'lat': 45.669, 'lng': 9.704},
            {'code': 'PMO', 'name': 'Palermo', 'city': 'Palermo',
             'country': 'Italy', 'country_code': 'it', 'schengen': True,
             'lat': 38.176, 'lng': 13.091},
        ]
        mock_searcher.config = {'max_price': 100, 'currency': 'EUR', 'origin_airport': 'VLC'}

        mock_searcher.search_flights.return_value = [{
            'totalPrice': 45.0,
            'outbound': {
                'destinationName': 'Milan Bergamo', 'destination': 'BGY',
                'departureTime': datetime(2026, 5, 20, 10, 0),
                'arrivalTime': datetime(2026, 5, 20, 12, 0),
                'flightNumber': 'FR 123', 'currency': 'EUR',
            },
            'inbound': {
                'departureTime': datetime(2026, 5, 21, 18, 0),
                'arrivalTime': datetime(2026, 5, 21, 20, 0),
                'flightNumber': 'FR 456',
            },
            'nights': 1,
            'stay_duration_hours': 30.0,
        }, {
            'totalPrice': 62.5,
            'outbound': {
                'destinationName': 'Palermo', 'destination': 'PMO',
                'departureTime': datetime(2026, 5, 20, 6, 0),
                'arrivalTime': datetime(2026, 5, 20, 8, 30),
                'flightNumber': 'FR 789', 'currency': 'EUR',
            },
            'inbound': {
                'departureTime': datetime(2026, 5, 21, 22, 0),
                'arrivalTime': datetime(2026, 5, 22, 0, 30),
                'flightNumber': 'FR 790',
            },
            'nights': 1,
            'stay_duration_hours': 40.0,
        }]
        mock_searcher.get_data_freshness.return_value = {
            'from_cache': False, 'stale': False, 'age_minutes': 0,
        }
        mock_searcher.search_nomad_routes.return_value = [{
            'origin': 'VLC',
            'legs': [{
                'destination': 'BGY', 'destination_name': 'Milan Bergamo',
                'country': 'Italy', 'flight_number': 'FR 123',
                'departure_time': '2026-05-20T10:00:00',
                'arrival_time': '2026-05-20T12:00:00',
                'price': 25.0, 'currency': 'EUR', 'stay_nights': 2,
            }],
            'return_flight': {
                'flight_number': 'FR 456',
                'departure_time': '2026-05-22T18:00:00',
                'arrival_time': '2026-05-22T20:00:00',
                'price': 20.0, 'currency': 'EUR',
            },
            'total_price': 45.0, 'currency': 'EUR',
        }, {
            'origin': 'VLC',
            'legs': [{
                'destination': 'PMO', 'destination_name': 'Palermo',
                'country': 'Italy', 'flight_number': 'FR 789',
                'departure_time': '2026-05-20T06:00:00',
                'arrival_time': '2026-05-20T08:30:00',
                'price': 30.0, 'currency': 'EUR', 'stay_nights': 3,
            }],
            'return_flight': {
                'flight_number': 'FR 790',
                'departure_time': '2026-05-23T22:00:00',
                'arrival_time': '2026-05-24T00:30:00',
                'price': 32.5, 'currency': 'EUR',
            },
            'total_price': 62.5, 'currency': 'EUR',
        }]

        from app import app
        app.config['TESTING'] = True

        def run_server():
            app.run(host='127.0.0.1', port=5099, use_reloader=False)

        t = threading.Thread(target=run_server, daemon=True)
        t.start()
        time.sleep(1)  # ждём старта сервера

        yield mock_searcher


BASE = 'http://127.0.0.1:5099'


class TestPageLoad:
    """Тесты загрузки страницы."""

    def test_page_loads(self, flask_server, page):
        page.goto(BASE)
        assert page.title() != ''
        assert 'Ryanair' in page.title() and 'FlyNomad' in page.title()

    def test_has_search_form(self, flask_server, page):
        page.goto(BASE)
        form = page.locator('#search-form')
        assert form.is_visible()

    def test_has_origin_select(self, flask_server, page):
        page.goto(BASE)
        select = page.locator('#origin-select')
        assert select.is_visible()
        # Аэропорты загружаются при старте модуля (реальные данные)
        options = select.locator('option')
        assert options.count() >= 3

    def test_has_date_input(self, flask_server, page):
        page.goto(BASE)
        date_input = page.locator('#departure-date')
        assert date_input.is_visible()

    def test_has_date_arrows(self, flask_server, page):
        page.goto(BASE)
        assert page.locator('#date-prev').is_visible()
        assert page.locator('#date-next').is_visible()

    def test_has_search_button(self, flask_server, page):
        page.goto(BASE)
        btn = page.locator('#btn-nomad-start')
        assert btn.is_visible()
        assert btn.text_content().strip() != ''


class TestSEO:
    """Тесты SEO-элементов."""

    def test_has_meta_description(self, flask_server, page):
        page.goto(BASE)
        meta = page.locator('meta[name="description"]')
        assert meta.get_attribute('content') != ''

    def test_has_open_graph(self, flask_server, page):
        page.goto(BASE)
        assert page.locator('meta[property="og:title"]').count() == 1
        assert page.locator('meta[property="og:description"]').count() == 1
        assert page.locator('meta[property="og:type"]').count() == 1

    def test_has_json_ld(self, flask_server, page):
        page.goto(BASE)
        ld = page.locator('script[type="application/ld+json"]')
        assert ld.count() == 1

    def test_has_lang_attribute(self, flask_server, page):
        page.goto(BASE)
        lang = page.locator('html').get_attribute('lang')
        assert lang in ('en', 'es', 'it', 'fr', 'pt', 'de', 'ru')

    def test_has_canonical(self, flask_server, page):
        page.goto(BASE)
        assert page.locator('link[rel="canonical"]').count() == 1


class TestSemanticHTML:
    """Тесты семантической разметки."""

    def test_has_header(self, flask_server, page):
        page.goto(BASE)
        assert page.locator('header').count() >= 1

    def test_has_main(self, flask_server, page):
        page.goto(BASE)
        assert page.locator('main').count() == 1

    def test_has_footer(self, flask_server, page):
        page.goto(BASE)
        assert page.locator('footer').count() == 1

    def test_has_h1(self, flask_server, page):
        page.goto(BASE)
        h1 = page.locator('h1')
        assert h1.count() == 1
        assert h1.text_content().strip() != ''


class TestSearch:
    """Тесты поиска маршрутов."""

    def test_search_shows_results(self, flask_server, page):
        page.goto(BASE)
        page.locator('#departure-date').fill('2026-05-20')
        page.locator('#btn-nomad-start').click()
        page.wait_for_selector('.route-card', timeout=15000)
        cards = page.locator('.route-card')
        assert cards.count() == 2

    def test_search_shows_price(self, flask_server, page):
        page.goto(BASE)
        page.locator('#departure-date').fill('2026-05-20')
        page.locator('#btn-nomad-start').click()
        page.wait_for_selector('.route-price', timeout=15000)
        first_price = page.locator('.route-price').first
        assert '45' in first_price.text_content()

    def test_search_shows_destination(self, flask_server, page):
        page.goto(BASE)
        page.locator('#departure-date').fill('2026-05-20')
        page.locator('#btn-nomad-start').click()
        page.wait_for_selector('.route-card', timeout=15000)
        first_card = page.locator('.route-card').first.text_content()
        assert 'Milan Bergamo' in first_card or 'BGY' in first_card

    def test_search_shows_return_flight(self, flask_server, page):
        page.goto(BASE)
        page.locator('#departure-date').fill('2026-05-20')
        page.locator('#btn-nomad-start').click()
        page.wait_for_selector('.route-card', timeout=15000)
        # Return flight icon should be present
        ret_icons = page.locator('.leg-icon.ret')
        assert ret_icons.count() >= 1


class TestMultiSelect:
    """Тесты multi-select dropdowns."""

    def test_country_dropdown_opens(self, flask_server, page):
        page.goto(BASE)
        btn = page.locator('#ms-countries .ms-btn')
        btn.click()
        panel = page.locator('#ms-countries .ms-panel')
        assert panel.is_visible()

    def test_country_dropdown_has_items(self, flask_server, page):
        page.goto(BASE)
        page.locator('#ms-countries .ms-btn').click()
        items = page.locator('#ms-countries .country-item')
        assert items.count() >= 2  # Italy, Spain

    def test_airport_dropdown_opens(self, flask_server, page):
        page.goto(BASE)
        page.locator('#ms-airports .ms-btn').click()
        panel = page.locator('#ms-airports .ms-panel')
        assert panel.is_visible()

    def test_dropdown_search_filters(self, flask_server, page):
        page.goto(BASE)
        page.locator('#ms-countries .ms-btn').click()
        search = page.locator('#ms-countries .ms-search')
        search.fill('Italy')
        visible_items = page.locator('#ms-countries .country-item:visible')
        assert visible_items.count() == 1

    def test_dropdown_closes_on_outside_click(self, flask_server, page):
        page.goto(BASE)
        page.locator('#ms-countries .ms-btn').click()
        assert page.locator('#ms-countries .ms-panel').is_visible()
        page.locator('h1').click()
        assert not page.locator('#ms-countries .ms-panel').is_visible()


class TestDateNavigation:
    """Тесты навигации по датам."""

    def test_next_day_button(self, flask_server, page):
        page.goto(BASE)
        date_input = page.locator('#departure-date')
        original = date_input.input_value()
        page.locator('#date-next').click()
        page.wait_for_timeout(500)
        new_date = date_input.input_value()
        assert new_date != original

    def test_prev_day_button(self, flask_server, page):
        page.goto(BASE)
        date_input = page.locator('#departure-date')
        original = date_input.input_value()
        page.locator('#date-prev').click()
        page.wait_for_timeout(500)
        new_date = date_input.input_value()
        assert new_date != original


class TestDarkMode:
    """Тесты тёмной темы."""

    def test_dark_mode_applies(self, flask_server, page):
        page.emulate_media(color_scheme='dark')
        page.goto(BASE)
        bg = page.evaluate('getComputedStyle(document.body).backgroundColor')
        # В dark mode фон должен быть тёмным (не белый/светло-серый)
        assert bg != 'rgb(246, 247, 249)'  # --bg light value

    def test_light_mode_default(self, flask_server, page):
        page.emulate_media(color_scheme='light')
        page.goto(BASE)
        bg = page.evaluate('getComputedStyle(document.body).backgroundColor')
        assert bg == 'rgb(246, 247, 249)'


class TestAccessibility:
    """Тесты доступности."""

    def test_skip_link_exists(self, flask_server, page):
        page.goto(BASE)
        skip = page.locator('.skip-link')
        assert skip.count() == 1

    def test_form_labels_present(self, flask_server, page):
        page.goto(BASE)
        # Каждый input/select должен иметь label
        inputs_with_id = page.locator('#search-form input[id], #search-form select[id]')
        for i in range(inputs_with_id.count()):
            el = inputs_with_id.nth(i)
            el_id = el.get_attribute('id')
            if el_id and el.get_attribute('type') != 'hidden':
                label = page.locator(f'label[for="{el_id}"]')
                assert label.count() >= 1, f"No label for #{el_id}"

    def test_aria_live_region(self, flask_server, page):
        page.goto(BASE)
        live = page.locator('[aria-live]')
        assert live.count() >= 1


class TestRouteResults:
    """Тесты отображения результатов маршрутов."""

    def test_routes_sorted_by_price(self, flask_server, page):
        page.goto(BASE)
        page.locator('#departure-date').fill('2026-05-20')
        page.locator('#btn-nomad-start').click()
        page.wait_for_selector('.route-card', timeout=15000)

        prices = page.locator('.route-price')
        first_price = prices.nth(0).text_content()
        second_price = prices.nth(1).text_content()
        assert '45' in first_price
        assert '62' in second_price

    def test_route_has_legs(self, flask_server, page):
        page.goto(BASE)
        page.locator('#departure-date').fill('2026-05-20')
        page.locator('#btn-nomad-start').click()
        page.wait_for_selector('.route-card', timeout=15000)

        legs = page.locator('.route-leg')
        # 2 routes x 2 legs each (outbound + return) = 4
        assert legs.count() == 4


class TestMobileLayout:
    """Тесты мобильной верстки."""

    def test_routes_visible_on_mobile(self, flask_server, page):
        page.set_viewport_size({'width': 375, 'height': 812})
        page.goto(BASE)
        page.locator('#departure-date').fill('2026-05-20')
        page.locator('#btn-nomad-start').click()
        page.wait_for_selector('.route-card', timeout=15000)
        cards = page.locator('.route-card')
        assert cards.count() == 2

    def test_routes_visible_on_desktop(self, flask_server, page):
        page.set_viewport_size({'width': 1280, 'height': 800})
        page.goto(BASE)
        page.locator('#departure-date').fill('2026-05-20')
        page.locator('#btn-nomad-start').click()
        page.wait_for_selector('.route-card', timeout=15000)
        assert page.locator('.route-card').count() == 2

    def test_form_usable_on_mobile(self, flask_server, page):
        page.set_viewport_size({'width': 375, 'height': 812})
        page.goto(BASE)
        assert page.locator('#origin-select').is_visible()
        assert page.locator('#departure-date').is_visible()
        assert page.locator('#btn-nomad-start').is_visible()


class TestI18n:
    """Тесты интернационализации."""

    def test_default_language_is_english(self, flask_server, page):
        page.goto(BASE)
        assert page.locator('html').get_attribute('lang') == 'en'
        assert 'Search routes' in page.locator('#btn-nomad-start').text_content()

    def test_switch_to_russian(self, flask_server, page):
        page.goto(f'{BASE}/?lang=ru')
        assert page.locator('html').get_attribute('lang') == 'ru'
        assert 'маршруты' in page.locator('#btn-nomad-start').text_content().lower()

    def test_switch_to_spanish(self, flask_server, page):
        page.goto(f'{BASE}/?lang=es')
        assert page.locator('html').get_attribute('lang') == 'es'
        assert 'Buscar rutas' in page.locator('#btn-nomad-start').text_content()

    def test_switch_to_german(self, flask_server, page):
        page.goto(f'{BASE}/?lang=de')
        assert page.locator('html').get_attribute('lang') == 'de'
        assert 'Routen suchen' in page.locator('#btn-nomad-start').text_content()

    def test_switch_to_italian(self, flask_server, page):
        page.goto(f'{BASE}/?lang=it')
        assert page.locator('html').get_attribute('lang') == 'it'
        assert 'Cerca percorsi' in page.locator('#btn-nomad-start').text_content()

    def test_switch_to_french(self, flask_server, page):
        page.goto(f'{BASE}/?lang=fr')
        assert page.locator('html').get_attribute('lang') == 'fr'
        assert 'Rechercher' in page.locator('#btn-nomad-start').text_content()

    def test_switch_to_portuguese(self, flask_server, page):
        page.goto(f'{BASE}/?lang=pt')
        assert page.locator('html').get_attribute('lang') == 'pt'
        assert 'Pesquisar rotas' in page.locator('#btn-nomad-start').text_content()

    def test_lang_switcher_visible(self, flask_server, page):
        page.goto(BASE)
        links = page.locator('.lang-link')
        assert links.count() == 7

    def test_lang_preserved_on_page(self, flask_server, page):
        page.goto(f'{BASE}/?lang=ru')
        assert page.locator('html').get_attribute('lang') == 'ru'
        # Button should be in Russian
        assert 'маршруты' in page.locator('#btn-nomad-start').text_content().lower()

    def test_invalid_lang_falls_back_to_english(self, flask_server, page):
        page.goto(f'{BASE}/?lang=xx')
        assert page.locator('html').get_attribute('lang') == 'en'

    def test_results_translated(self, flask_server, page):
        page.goto(f'{BASE}/?lang=es')
        page.locator('#departure-date').fill('2026-05-20')
        page.locator('#btn-nomad-start').click()
        page.wait_for_selector('.route-card', timeout=15000)
        # Results header should be in Spanish
        header = page.locator('.results-count').text_content()
        assert 'rutas' in header.lower()
