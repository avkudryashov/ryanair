// ── Geolocation ──
const originSelect = document.getElementById('origin-select');

function warmOrigin(code) {
    fetch('/api/warm', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({origin: code})
    }).catch(() => {});
}

function selectNearestAirport(lat, lng) {
    let minDist = Infinity, nearest = null;
    for (const [code, coords] of Object.entries(airportCoords)) {
        const dlat = coords.lat - lat, dlng = coords.lng - lng;
        const dist = dlat * dlat + dlng * dlng;
        if (dist < minDist) { minDist = dist; nearest = code; }
    }
    if (nearest && !new URLSearchParams(location.search).get('origin')) {
        originSelect.value = nearest;
        warmOrigin(nearest);
    }
}

if (navigator.geolocation && !new URLSearchParams(location.search).get('origin')) {
    navigator.geolocation.getCurrentPosition(
        pos => selectNearestAirport(pos.coords.latitude, pos.coords.longitude),
        () => {}
    );
}

originSelect.addEventListener('change', () => {
    warmOrigin(originSelect.value);
    loadDestinations();
});

// ── Multi-select ──
function initMultiSelect(container, hiddenInput, opts = {}) {
    const btn = container.querySelector('.ms-btn');
    const panel = container.querySelector('.ms-panel');
    const search = panel.querySelector('.ms-search');
    const textEl = btn.querySelector('.ms-text');
    const checkboxes = panel.querySelectorAll('input[type=checkbox]');
    const placeholder = opts.placeholder || '…';

    function updateText() {
        const checked = [...checkboxes].filter(cb => cb.checked && !cb.value.startsWith('__country__'));
        if (checked.length === 0) {
            textEl.textContent = placeholder;
            textEl.classList.add('placeholder');
        } else if (checked.length <= 3) {
            textEl.textContent = checked.map(cb => cb.parentElement.textContent.trim()).join(', ');
            textEl.classList.remove('placeholder');
        } else {
            textEl.textContent = I18N.selected_count.replace('{n}', checked.length);
            textEl.classList.remove('placeholder');
        }
    }

    function updateHidden() {
        const vals = [...checkboxes]
            .filter(cb => cb.checked && !cb.value.startsWith('__country__'))
            .map(cb => cb.value);
        hiddenInput.value = vals.join(',');
    }

    btn.addEventListener('click', e => {
        e.stopPropagation();
        const isOpen = panel.classList.contains('open');
        closeAllPanels();
        if (!isOpen) {
            panel.classList.add('open');
            btn.classList.add('open');
            btn.setAttribute('aria-expanded', 'true');
            search.focus();
        }
    });

    search.addEventListener('input', () => {
        const q = search.value.toLowerCase();
        panel.querySelectorAll('.ms-item').forEach(item => {
            item.style.display = item.textContent.toLowerCase().includes(q) ? '' : 'none';
        });
    });

    checkboxes.forEach(cb => {
        cb.addEventListener('change', () => {
            if (opts.onChangeCallback) opts.onChangeCallback(cb);
            updateText();
            updateHidden();
        });
    });

    panel.addEventListener('click', e => e.stopPropagation());

    // Restore from URL
    const currentVal = hiddenInput.value;
    if (currentVal) {
        const vals = new Set(currentVal.split(',').map(v => v.trim()).filter(Boolean));
        checkboxes.forEach(cb => { if (vals.has(cb.value)) cb.checked = true; });
    }
    updateText();

    return { checkboxes, updateText, updateHidden };
}

function closeAllPanels() {
    document.querySelectorAll('.ms-panel').forEach(p => p.classList.remove('open'));
    document.querySelectorAll('.ms-btn').forEach(b => {
        b.classList.remove('open');
        b.setAttribute('aria-expanded', 'false');
    });
}
document.addEventListener('click', closeAllPanels);

// ── Init multi-selects ──
const msCountries = initMultiSelect(
    document.getElementById('ms-countries'),
    document.getElementById('excl-countries-input'),
    {
        placeholder: I18N.select_countries,
        onChangeCallback(cb) {
            const country = cb.value;
            const codes = countryToAirports[country] || [];
            const airportPanel = document.getElementById('ms-airports');
            codes.forEach(code => {
                const acb = airportPanel.querySelector(`input[value="${code}"]`);
                if (acb) acb.checked = cb.checked;
            });
            const groupCb = airportPanel.querySelector(`input[value="__country__${country}"]`);
            if (groupCb) groupCb.checked = cb.checked;
            msAirports.updateText();
            msAirports.updateHidden();
        }
    }
);

const msAirports = initMultiSelect(
    document.getElementById('ms-airports'),
    document.getElementById('excl-airports-input'),
    {
        placeholder: I18N.select_airports,
        onChangeCallback(cb) {
            if (cb.value.startsWith('__country__')) {
                const country = cb.value.replace('__country__', '');
                const panel = cb.closest('.ms-panel');
                panel.querySelectorAll(`[data-airport-country="${country}"] input`).forEach(acb => {
                    acb.checked = cb.checked;
                });
            } else {
                const country = cb.closest('[data-airport-country]')?.dataset.airportCountry;
                if (country) {
                    const panel = cb.closest('.ms-panel');
                    const group = panel.querySelectorAll(`[data-airport-country="${country}"] input`);
                    const allChecked = [...group].every(a => a.checked);
                    const groupCb = panel.querySelector(`input[value="__country__${country}"]`);
                    if (groupCb) groupCb.checked = allChecked;
                }
            }
        }
    }
);

// Restore cascade on load
(function() {
    const val = document.getElementById('excl-countries-input').value;
    if (!val) return;
    const selected = val.split(',').map(v => v.trim()).filter(Boolean);
    const panel = document.getElementById('ms-airports');
    selected.forEach(country => {
        (countryToAirports[country] || []).forEach(code => {
            const acb = panel.querySelector(`input[value="${code}"]`);
            if (acb) acb.checked = true;
        });
        const g = panel.querySelector(`input[value="__country__${country}"]`);
        if (g) g.checked = true;
    });
    msAirports.updateText();
    msAirports.updateHidden();
})();

// ── Date arrows (HTMX-aware) ──
(function() {
    const dateInput = document.getElementById('departure-date');
    function shiftDate(days) {
        const d = new Date(dateInput.value);
        d.setDate(d.getDate() + days);
        dateInput.value = d.toISOString().slice(0, 10);
    }
    document.getElementById('date-prev').addEventListener('click', () => shiftDate(-1));
    document.getElementById('date-next').addEventListener('click', () => shiftDate(1));
})();

// ── Table sorting (works on initial + HTMX-swapped content) ──
function initSorting() {
    const table = document.getElementById('results-table');
    if (!table) return;
    table.querySelectorAll('th.sortable').forEach(th => {
        th.addEventListener('click', () => {
            const col = parseInt(th.dataset.col);
            const type = th.dataset.sort;
            const isAsc = th.classList.contains('asc');
            const dir = isAsc ? 'desc' : 'asc';

            table.querySelectorAll('th.sortable').forEach(h => {
                h.classList.remove('sorted', 'asc', 'desc');
                const icon = h.querySelector('.sort-icon');
                if (icon) icon.textContent = '';
            });

            th.classList.add('sorted', dir);
            let icon = th.querySelector('.sort-icon');
            if (!icon) { icon = document.createElement('span'); icon.className = 'sort-icon'; th.appendChild(icon); }
            icon.textContent = dir === 'asc' ? ' \u25B2' : ' \u25BC';
            th.setAttribute('aria-sort', dir === 'asc' ? 'ascending' : 'descending');

            const tbody = table.querySelector('tbody');
            const rows = [...tbody.querySelectorAll('tr')];
            rows.sort((a, b) => {
                const aVal = a.children[col].dataset.val;
                const bVal = b.children[col].dataset.val;
                let cmp = type === 'number' ? parseFloat(aVal) - parseFloat(bVal) : aVal.localeCompare(bVal);
                return dir === 'asc' ? cmp : -cmp;
            });
            rows.forEach((row, i) => {
                row.querySelector('.row-num').textContent = i + 1;
                tbody.appendChild(row);
            });
        });
    });
}
initSorting();

// ── Language switcher: preserve current params ──
document.querySelectorAll('.lang-link').forEach(link => {
    link.addEventListener('click', e => {
        e.preventDefault();
        const url = new URL(location.href);
        url.searchParams.set('lang', link.href.split('lang=')[1]);
        location.href = url.toString();
    });
});

// ── Route search ──
(function() {
    const resultsArea = document.getElementById('results-area');

    // ── Nomad auto-routes ──
    const lang = document.querySelector('input[name="lang"]')?.value || 'en';
    function fmtDate(iso) { return new Date(iso).toLocaleDateString(lang, { day: '2-digit', month: '2-digit' }); }
    function fmtTime(iso) { return iso.slice(11, 16); }
    function buildRyanairUrl(origin, dest, date) {
        const d = date.slice(0, 10);
        const p = new URLSearchParams({
            adults: 1, teens: 0, children: 0, infants: 0,
            dateOut: d, dateIn: '', isConnectedFlight: 'false', isReturn: 'false',
            discount: 0, promoCode: '', originIata: origin, destinationIata: dest,
            tpAdults: 1, tpTeens: 0, tpChildren: 0, tpInfants: 0,
            tpStartDate: d, tpEndDate: '', tpDiscount: 0, tpPromoCode: '',
            tpOriginIata: origin, tpDestinationIata: dest,
        });
        return 'https://www.ryanair.com/gb/en/trip/flights/select?' + p.toString();
    }

    function fmtStay(n) {
        // I18N.nomad_stay = ["1 night", "2 nights", "5 nights"] — pick form & replace number
        const form = n === 1 ? 0 : (n < 5 ? 1 : 2);
        const tmpl = I18N.nomad_stay[form];
        return tmpl.replace(/\d+/, n);
    }

    async function searchNomadRoutes() {
        const origin = document.getElementById('origin-select').value;
        const departureDate = document.getElementById('departure-date').value;
        const nights = document.getElementById('nomad-nights').value || '1,2,3';
        const hops = document.getElementById('nomad-hops').value || '2';
        const maxPrice = document.getElementById('max-price').value || '50';
        const topN = document.getElementById('top-n').value || '10';

        if (!origin || !departureDate) return;

        const exclCountries = document.getElementById('excl-countries-input').value;
        const exclAirports = document.getElementById('excl-airports-input').value;

        const p = new URLSearchParams({
            origin, departure_date: departureDate,
            nights, hops, max_price: maxPrice, top_n: topN,
        });
        if (exclCountries) p.set('excl_countries', exclCountries);
        if (exclAirports) p.set('excl_airports', exclAirports);

        resultsArea.innerHTML = `<div class="tree-loading"><div class="plane-fly"><span class="trail"></span>&#9992;&#xFE0E;</div> ${I18N.nomad_searching}</div>`;

        try {
            const r = await fetch('/api/nomad/routes?' + p);
            const data = await r.json();
            if (data.error) {
                resultsArea.innerHTML = `<div class="alert alert-error">${data.error}</div>`;
                return;
            }
            renderNomadRoutes(data.routes || [], origin);
        } catch (e) {
            resultsArea.innerHTML = `<div class="alert alert-error">Ошибка: ${e.message}</div>`;
        }
    }

    function renderNomadRoutes(routes, origin) {
        if (!routes.length) {
            resultsArea.innerHTML = `<div class="empty-state"><p>${I18N.nomad_no_routes}</p></div>`;
            return;
        }

        let html = `<div class="results-header"><p class="results-count">${I18N.nomad_routes_found.replace('{N}', routes.length)}</p></div>`;

        routes.forEach((route, ri) => {
            let legs = '';

            route.legs.forEach((leg, li) => {
                const prev = li === 0 ? origin : route.legs[li - 1].destination;
                legs += `<div class="route-leg">`;
                legs += `<div class="leg-icon hop">&#9992;</div>`;
                legs += `<div class="leg-from-to">${prev} &rarr; ${leg.destination}</div>`;
                legs += `<div class="leg-details">${fmtDate(leg.departure_time)} ${fmtTime(leg.departure_time)}&rarr;${fmtTime(leg.arrival_time)} <span style="font-family:var(--font-mono);font-size:11px">${leg.flight_number}</span></div>`;
                legs += `<div class="leg-price">${leg.price} ${leg.currency}</div>`;
                legs += `<a class="leg-book" href="${buildRyanairUrl(prev, leg.destination, leg.departure_time)}" target="_blank" rel="noopener">Book</a>`;
                legs += `</div>`;

                // Stay info
                if (leg.stay_nights) {
                    legs += `<div class="route-stay">${leg.destination_name} — ${fmtStay(leg.stay_nights)}</div>`;
                }
            });

            // Return leg
            const rf = route.return_flight;
            const lastDest = route.legs[route.legs.length - 1].destination;
            legs += `<div class="route-leg">`;
            legs += `<div class="leg-icon ret">&#8617;</div>`;
            legs += `<div class="leg-from-to">${lastDest} &rarr; ${origin}</div>`;
            legs += `<div class="leg-details">${fmtDate(rf.departure_time)} ${fmtTime(rf.departure_time)}&rarr;${fmtTime(rf.arrival_time)} <span style="font-family:var(--font-mono);font-size:11px">${rf.flight_number}</span></div>`;
            legs += `<div class="leg-price">${rf.price} ${rf.currency}</div>`;
            legs += `<a class="leg-book" href="${buildRyanairUrl(lastDest, origin, rf.departure_time)}" target="_blank" rel="noopener">Book</a>`;
            legs += `</div>`;

            const cities = route.legs.map(l => l.destination_name).join(' &rarr; ');
            html += `<div class="route-card">`;
            html += `<div class="route-header">`;
            html += `<div class="route-title">${origin} &rarr; ${cities} &rarr; ${origin}</div>`;
            html += `<div class="route-price">${route.total_price} ${route.currency}</div>`;
            html += `</div>`;
            html += legs;
            html += `</div>`;
        });

        resultsArea.innerHTML = html;
    }

    // ── Nomad start button ──
    document.getElementById('btn-nomad-start').addEventListener('click', searchNomadRoutes);
})();
