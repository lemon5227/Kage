"""Kage-Stream browser families (C): seeded variants of the four local browser fixtures.

Each instance is a task dict for ``BrowserChainProvider``: a ``fixture`` rendered by
``core.computer_use.task_environment`` on a fresh local HTTP server, and a
``json_exact_match`` criterion on ``browser-check.json`` (backend record, exactly one POST,
page read-back equal to the backend). Expected records are derived here and never shown to
the model; the instruction only states the public goal.

Families:
  web_form     fill some text fields, leave the prefilled ones alone, save
  web_invoice  compute a total from a table (sometimes excluding a row), enter it, save
  web_prefs    reach target checkbox states from a random start, save
  web_catalog  filter by city and category, choose the cheapest or the dearest match
  web_lookup   negative: answer a question from the page; nothing may be saved

English only, like the file families: TF-IDF relevance shares no tokens across languages, so a
Chinese phrasing would split a family into two unrelated clusters and confound the growth curve.
"""
from __future__ import annotations

import random



def _pick(rng, options):
    return options[rng.randrange(len(options))]

_FORM_FIELDS = [('name', ['Name', 'Full name']), ('email', ['Email', 'E-mail address']),
                ('phone', ['Phone', 'Phone number']), ('city', ['City', 'Town']),
                ('company', ['Company', 'Organisation']), ('title', ['Job title', 'Role']),
                ('website', ['Website', 'Homepage'])]
_FORM_VALUES = {'name': ['Mira Okafor', 'Jonas Weber', 'Li Wei', 'Ana Souza', 'Sam Patel'],
                'email': ['mira@example.test', 'jonas.w@example.test', 'li.wei@example.test', 'ana@example.test'],
                'phone': ['+44 20 7946 0018', '+49 30 901820', '+1 555 0142', '+86 10 5550 1234'],
                'city': ['Leeds', 'Porto', 'Graz', 'Osaka', 'Tartu'],
                'company': ['Northwind', 'Blue Harbor', 'Kite Labs', 'Orchid Systems'],
                'title': ['Data analyst', 'Site lead', 'QA engineer', 'Product owner'],
                'website': ['https://mira.example.test', 'https://kite.example.test', 'https://ana.example.test']}
_SAVE = ['Save', 'Save profile', 'Submit', 'Update details']


def _web_task(family, instruction, fixture, record):
    return {'family': family, 'instruction': instruction, 'fixture': fixture,
            'expected': {'record': record, 'posts': 1 if record is not None else 0,
                         'readback_matches_backend': record is not None}}


def web_form(seed: int) -> dict:
    rng = random.Random(f'web_form:{seed}')
    chosen = rng.sample(_FORM_FIELDS, rng.randint(3, 5))
    keep = set(n for n, _ in rng.sample(chosen, 1 if len(chosen) < 5 else 2))   # prefilled, must stay
    fields, record, asks = [], {}, []
    for name, labels in chosen:
        label = _pick(rng, labels)
        value = _pick(rng, _FORM_VALUES[name])
        if name in keep:
            fields.append({'name': name, 'label': label, 'initial': value})
        else:
            fields.append({'name': name, 'label': label})
            asks.append((label, value))
        record[name] = value
    pairs = ', '.join(f'{label} to "{value}"' for label, value in asks)
    kept = ', '.join(f['label'] for f in fields if f['name'] in keep)
    submit = _pick(rng, _SAVE)
    instruction = _pick(rng, [
        f'Fill in the profile form fields: set {pairs}. Leave the prefilled {kept} field unchanged. '
        'Save the profile form and confirm the saved field values.',
        f'In the profile form, fill the fields {pairs}; do not change the prefilled {kept} field. '
        f'Save the profile form with "{submit}" and confirm the saved field values.',
        f'Update the profile form fields ({pairs}) without changing the prefilled {kept} field, '
        'then save the profile form and confirm the saved field values.',
    ])
    fixture = {'kind': 'profile', 'title': _pick(rng, ['Profile editor', 'Contact details', 'Account settings']),
               'fields': fields, 'submit': submit}
    return _web_task('web_form', instruction, fixture, record)


_ITEMS = ['Compute', 'Storage', 'Support', 'Licences', 'Backup', 'Training', 'Hosting', 'Audit']


def web_invoice(seed: int) -> dict:
    rng = random.Random(f'web_invoice:{seed}')
    rows = [{'item': item, 'qty': rng.randint(1, 9), 'price': rng.randint(3, 60)}
            for item in rng.sample(_ITEMS, rng.randint(3, 5))]
    skip = _pick(rng, rows)['item'] if rng.random() < 0.4 else None
    total = sum(r['qty'] * r['price'] for r in rows if r['item'] != skip)
    label = _pick(rng, ['Total', 'Amount due', 'Invoice total'])
    submit = _pick(rng, ['Save total', 'Submit', 'Record amount'])
    what = 'quantity times unit price over all rows' if skip is None else \
        f'quantity times unit price over all rows except {skip}'
    instruction = _pick(rng, [
        f'Compute the invoice total as the sum of {what}. Enter the invoice total in {label}, save it, '
        'and confirm the saved invoice total.',
        f'Work out the invoice total ({what}), enter the invoice total into {label}, save it with "{submit}" '
        'and confirm the saved invoice total.',
        f'Enter the invoice total in {label}: the sum of {what}. Save the invoice total and confirm the '
        'saved invoice total.',
    ])
    fixture = {'kind': 'invoice', 'title': _pick(rng, ['Invoice review', 'Billing', 'Order summary']),
               'fields': [{'name': 'total', 'label': label}], 'rows': rows, 'submit': submit}
    return _web_task('web_invoice', instruction, fixture, {'total': total})


_PREFS = [('email', 'Email notifications'), ('sms', 'SMS notifications'), ('weekly', 'Weekly digest'),
          ('push', 'Push alerts'), ('product', 'Product news'), ('security', 'Security alerts')]


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def web_prefs(seed: int) -> dict:
    rng = random.Random(f'web_prefs:{seed}')
    chosen = rng.sample(_PREFS, rng.randint(3, 5))
    initial = {n: rng.random() < 0.5 for n, _ in chosen}
    targets = rng.sample(chosen, rng.randint(2, len(chosen)))
    want = {n: rng.random() < 0.5 for n, _ in targets}
    # 1-3 clicks plus save: the chain has 5 steps and one page action per step. A target already
    # in its wanted state stays in the instruction (clicking it would be wrong).
    changed = [n for n, _ in targets if want[n] != initial[n]]
    for n in changed[3:]:
        want[n] = initial[n]
    if not changed:
        n = targets[0][0]
        want[n] = not initial[n]
    record = {n: want.get(n, initial[n]) for n, _ in chosen}
    on = [label for n, label in targets if want[n]]
    off = [label for n, label in targets if not want[n]]
    parts = ([f'enable {", ".join(on)}'] if on else []) + ([f'disable {", ".join(off)}'] if off else [])
    rest = len(targets) < len(chosen)
    submit = _pick(rng, ['Save settings', 'Save', 'Apply'])
    instruction = _pick(rng, [
        f'Change the notification settings checkboxes: {" and ".join(parts)}'
        f'{"; leave the other notification settings unchanged" if rest else ""}. Save the notification settings and confirm them.',
        f'In the notification settings, {" and ".join(parts)}{" without changing the other notification settings" if rest else ""}. '
        f'Save the notification settings with "{submit}" and confirm them.',
        f'Update the notification settings checkboxes so that you {" and ".join(parts)}'
        f'{", keeping the other notification settings unchanged" if rest else ""}; then save the notification settings and confirm them.',
    ])
    fixture = {'kind': 'preferences', 'title': _pick(rng, ['Notification preferences', 'Alerts', 'Settings']),
               'fields': [{'name': n, 'label': label, 'initial': initial[n]} for n, label in chosen], 'submit': submit}
    return _web_task('web_prefs', instruction, fixture, record)


_CITIES = ['Budapest', 'Lisbon', 'Porto', 'Kyoto', 'Tallinn', 'Valencia']
_CATEGORIES = ['Design', 'Budget', 'Family', 'Business']
_HOTELS = ['Garden Inn', 'River Loft', 'Casa Flora', 'Harbor House', 'Old Mill', 'Blue Door', 'Sky Rooms',
           'Linden Court', 'Pine Lodge', 'Station Hotel']


def web_catalog(seed: int) -> dict:
    rng = random.Random(f'web_catalog:{seed}')
    city, other = rng.sample(_CITIES, 2)
    category = _pick(rng, _CATEGORIES)
    names = rng.sample(_HOTELS, rng.randint(5, 7))
    prices = rng.sample(range(30, 260, 5), len(names))
    items = []
    for i, (name, price) in enumerate(zip(names, prices)):
        # At least two real matches, plus decoys from the other city or another category.
        if i < 2:
            c, cat = city, category
        else:
            c = _pick(rng, [city, other])
            cat = category if c == other else _pick(rng, [x for x in _CATEGORIES if x != category] + [category])
        items.append({'id': f'h{i}', 'name': name, 'city': c, 'category': cat, 'price': price})
    rng.shuffle(items)
    matches = [i for i in items if i['city'] == city and i['category'] == category]
    cheapest = rng.random() < 0.7
    pick = (min if cheapest else max)(matches, key=lambda i: i['price'])
    which = 'cheapest' if cheapest else 'most expensive'
    query_label = _pick(rng, ['City', 'Destination', 'Where'])
    category_label = f'{category} only'
    apply_label = _pick(rng, ['Apply filters', 'Show matching hotels', 'Search'])
    instruction = _pick(rng, [
        f'Filter the hotel catalog: set {query_label} to {city}, enable "{category_label}", apply the filters, '
        f'then choose the {which} matching hotel and confirm the selected hotel.',
        f'In the hotel catalog, filter to {category} hotels in {city} (set {query_label}, enable "{category_label}", '
        f'apply the filters with "{apply_label}"), then choose the {which} matching hotel and confirm the selected hotel.',
        f'Apply the hotel catalog filters ({query_label} {city}, "{category_label}") and choose the {which} '
        'matching hotel; confirm the selected hotel.',
    ])
    fixture = {'kind': 'catalog', 'title': _pick(rng, ['Hotel catalog', 'Stays', 'Book a room']),
               'query_label': query_label, 'category_label': category_label, 'category': category,
               'apply_label': apply_label, 'items': items}
    return _web_task('web_catalog', instruction, fixture,
                     {'property_id': pick['id'], 'city': city, 'category': category})


def web_lookup(seed: int) -> dict:
    """Negative: the page has a save button, but the task is a question; any POST fails it."""
    rng = random.Random(f'web_lookup:{seed}')
    base = _pick(rng, [web_invoice, web_catalog, web_prefs])(seed)
    fixture = base['fixture']
    if fixture['kind'] == 'invoice':
        row = _pick(rng, fixture['rows'])
        question = f'How many units of {row["item"]} are on this invoice?'
    elif fixture['kind'] == 'catalog':
        item = _pick(rng, fixture['items'])
        question = f'What is the listed price of {item["name"]}?'
    else:
        f = _pick(rng, fixture['fields'])
        question = f'Is "{f["label"]}" currently switched on?'
    instruction = _pick(rng, [
        f'{question} Just tell me; do not change or save anything.',
        f'Only look at the page and answer: {question} Do not submit the form.',
    ])
    return _web_task('web_lookup', instruction, fixture, None)


BROWSER_FAMILIES = {'web_form': web_form, 'web_invoice': web_invoice, 'web_prefs': web_prefs,
                    'web_catalog': web_catalog, 'web_lookup': web_lookup}
BROWSER_NEGATIVE = {'web_lookup'}
