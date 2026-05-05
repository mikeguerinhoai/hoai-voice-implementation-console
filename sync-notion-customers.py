"""
Sync onboarding-tracker.json customers into the Notion Implementation Console DB.

Usage:
    python implementation-console/sync-notion-customers.py [--dry-run]

Steps:
    1. Load onboarding-tracker.json (filtered to configured cohorts)
    2. Load canonical names from Supabase management_company table
    3. Fuzzy-match tracker names to canonical names
    4. Query existing Notion DB rows
    5. Archive placeholder rows (Item 2-10, blank names)
    6. Create pages for customers not already in Notion
"""

import json
import os
import sys
import re
import difflib
import time
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)

# ── Config ──────────────────────────────────────────────────────────────────
with open(os.path.join(SCRIPT_DIR, 'implementation-config.json')) as f:
    CONFIG = json.load(f)

NOTION_API_KEY = os.environ.get('NOTION_API_KEY')
if not NOTION_API_KEY:
    print("ERROR: NOTION_API_KEY not found in .env file")
    print("  Add: NOTION_API_KEY=ntn_... to your .env file")
    sys.exit(1)

DATABASE_ID = CONFIG['notion']['database_id']
COHORTS_TO_SYNC = CONFIG['cohorts_to_sync']
RATE_LIMIT_DELAY = 0.5

HEADERS = {
    'Authorization': f'Bearer {NOTION_API_KEY}',
    'Content-Type': 'application/json',
    'Notion-Version': '2022-06-28',
}

# ── Fuzzy Name Matching (from onboarding-audit/fetch-onboarding-data.py) ───
_STRIP_RE = re.compile(
    r'\b(llc|inc|corp|management|property|properties|group|services|'
    r'company|association|associates|of)\b', re.IGNORECASE
)
_PUNCT_RE = re.compile(r'[,.\-\'\"]+')


def _normalize_name(name):
    if not name:
        return ''
    n = _STRIP_RE.sub('', name)
    n = _PUNCT_RE.sub(' ', n)
    return ' '.join(n.lower().split())


def match_names(canonical_names, external_names):
    """3-pass name matching: exact → normalized → fuzzy."""
    mapping = {}
    unmatched = list(external_names)

    lower_map = {n.strip().lower(): n for n in canonical_names}
    norm_map = {_normalize_name(n): n for n in canonical_names}

    # Pass 1: exact (lowercase, stripped)
    still_unmatched = []
    for ext in unmatched:
        key = ext.strip().lower()
        if key in lower_map:
            mapping[ext] = lower_map[key]
        else:
            still_unmatched.append(ext)
    unmatched = still_unmatched

    # Pass 2: normalized
    still_unmatched = []
    for ext in unmatched:
        key = _normalize_name(ext)
        if key and key in norm_map:
            mapping[ext] = norm_map[key]
        else:
            still_unmatched.append(ext)
    unmatched = still_unmatched

    # Pass 3: fuzzy (difflib with 0.75 cutoff + length ratio guard)
    canon_norm_list = list(norm_map.keys())
    for ext in unmatched:
        key = _normalize_name(ext)
        if not key or len(key) < 4:
            continue
        matches = difflib.get_close_matches(key, canon_norm_list, n=1, cutoff=0.75)
        if matches:
            # Guard: reject if length ratio is too different (avoids ACMGA→CMG)
            ratio = min(len(key), len(matches[0])) / max(len(key), len(matches[0]))
            if ratio >= 0.65:
                mapping[ext] = norm_map[matches[0]]

    return mapping


# ── Notion API Helpers ──────────────────────────────────────────────────────
def notion_request(method, url, json_body=None):
    """Rate-limited Notion API request with retry."""
    time.sleep(RATE_LIMIT_DELAY)
    for attempt in range(3):
        try:
            resp = requests.request(method, url, headers=HEADERS, json=json_body, timeout=30)
            if resp.status_code in (200, 201):
                return resp.json()
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = 2 ** attempt
                print(f"  WARN: {resp.status_code} — retrying in {wait}s")
                time.sleep(wait)
                continue
            print(f"  ERROR: {resp.status_code}: {resp.text[:300]}")
            return None
        except requests.exceptions.RequestException as e:
            wait = 2 ** attempt
            print(f"  WARN: Request error: {e} — retrying in {wait}s")
            time.sleep(wait)
    print(f"  ERROR: Max retries exceeded for {url}")
    return None


def query_all_pages():
    """Query all pages from the Implementation Console DB."""
    pages = []
    url = f'https://api.notion.com/v1/databases/{DATABASE_ID}/query'
    has_more = True
    start_cursor = None

    while has_more:
        body = {}
        if start_cursor:
            body['start_cursor'] = start_cursor
        result = notion_request('POST', url, body)
        if not result:
            break
        pages.extend(result.get('results', []))
        has_more = result.get('has_more', False)
        start_cursor = result.get('next_cursor')

    return pages


def get_page_title(page):
    """Extract Company Name (title) from a Notion page."""
    title_prop = page.get('properties', {}).get('Company Name', {})
    title_arr = title_prop.get('title', [])
    return title_arr[0].get('text', {}).get('content', '') if title_arr else ''


def archive_page(page_id):
    """Move a Notion page to trash."""
    url = f'https://api.notion.com/v1/pages/{page_id}'
    return notion_request('PATCH', url, {'archived': True})


def create_customer_page(name, cohort, annotation=None):
    """Create a new customer page in the Implementation Console DB."""
    url = 'https://api.notion.com/v1/pages'
    properties = {
        'Company Name': {
            'title': [{'text': {'content': name}}]
        },
        'Status': {
            'select': {'name': 'Not Started'}
        },
        'Current Stage': {
            'select': {'name': 'Welcome Package'}
        },
        'Health': {
            'select': {'name': 'Green'}
        },
        'Cohort': {
            'rich_text': [{'text': {'content': cohort}}]
        },
    }

    if annotation:
        properties['Implementation Notes'] = {
            'rich_text': [{'text': {'content': annotation}}]
        }

    body = {
        'parent': {'database_id': DATABASE_ID},
        'properties': properties,
    }
    return notion_request('POST', url, body)


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    dry_run = '--dry-run' in sys.argv

    print("=" * 60)
    print("HOAi Implementation Console — Customer Sync")
    print(f"  Cohorts: {', '.join(COHORTS_TO_SYNC)}")
    print(f"  Dry run: {dry_run}")
    print("=" * 60)

    # 1. Load onboarding tracker
    tracker_path = os.path.join(ROOT_DIR, 'onboarding-tracker.json')
    with open(tracker_path) as f:
        tracker = json.load(f)

    customers_to_sync = []
    for cohort_key in COHORTS_TO_SYNC:
        cohort_data = tracker.get('cohorts', {}).get(cohort_key, {})
        for cust in cohort_data.get('customers', []):
            customers_to_sync.append({
                'name': cust['name'],
                'cohort': cohort_key,
                'annotation': cust.get('annotation'),
            })

    # Also check failed_implementations for these cohorts
    excluded_names = set(tracker.get('excluded', []))
    failed_names = {f['name'] for f in tracker.get('failed_implementations', [])
                    if f.get('cohort') in COHORTS_TO_SYNC}

    # Filter out failed + excluded
    customers_to_sync = [
        c for c in customers_to_sync
        if c['name'] not in excluded_names and c['name'] not in failed_names
    ]

    print(f"\n  Customers from tracker: {len(customers_to_sync)}")
    for c in customers_to_sync:
        suffix = f" ({c['annotation']})" if c['annotation'] else ''
        print(f"    • {c['name']} [{c['cohort']}]{suffix}")

    # 2. Load canonical names from Supabase
    sys.path.insert(0, ROOT_DIR)
    from supabase.queries.management_companies import list_active
    canonical = list_active()
    canonical_names = [c['name'] for c in canonical]
    print(f"\n  Supabase canonical companies: {len(canonical_names)}")

    # 3. Fuzzy match
    tracker_names = [c['name'] for c in customers_to_sync]
    name_map = match_names(canonical_names, tracker_names)

    print(f"\n  Name matching results:")
    for c in customers_to_sync:
        matched = name_map.get(c['name'])
        if matched and matched != c['name']:
            print(f"    ✓ {c['name']}  →  {matched}")
        elif matched:
            print(f"    ✓ {c['name']}")
        else:
            print(f"    ✗ {c['name']}  (no Supabase match — using tracker name)")

    # Use canonical names where matched, tracker names otherwise
    for c in customers_to_sync:
        c['display_name'] = name_map.get(c['name'], c['name'])

    # 4. Query existing Notion pages
    print(f"\n  Querying existing Notion DB rows...")
    existing_pages = query_all_pages()
    print(f"  Found {len(existing_pages)} existing rows")

    existing_names = set()
    placeholder_pages = []

    for page in existing_pages:
        title = get_page_title(page)
        if not title or title.startswith('Item '):
            placeholder_pages.append(page)
            print(f"    [placeholder] '{title}' → will archive")
        else:
            existing_names.add(title.strip())
            print(f"    [existing] '{title}' → keeping")

    # 5. Archive placeholders
    print(f"\n  Archiving {len(placeholder_pages)} placeholder rows...")
    if not dry_run:
        for page in placeholder_pages:
            title = get_page_title(page) or '(blank)'
            result = archive_page(page['id'])
            status = 'OK' if result else 'FAILED'
            print(f"    Archived '{title}': {status}")
    else:
        for page in placeholder_pages:
            title = get_page_title(page) or '(blank)'
            print(f"    [DRY RUN] Would archive '{title}'")

    # 6. Create pages for new customers
    new_customers = [
        c for c in customers_to_sync
        if c['display_name'] not in existing_names
    ]
    skipped = [
        c for c in customers_to_sync
        if c['display_name'] in existing_names
    ]

    if skipped:
        print(f"\n  Skipping {len(skipped)} already-existing customers:")
        for c in skipped:
            print(f"    • {c['display_name']}")

    print(f"\n  Creating {len(new_customers)} new customer pages...")
    created = 0
    if not dry_run:
        for c in new_customers:
            result = create_customer_page(
                c['display_name'], c['cohort'], c['annotation']
            )
            if result:
                print(f"    ✓ Created: {c['display_name']}")
                created += 1
            else:
                print(f"    ✗ Failed: {c['display_name']}")
    else:
        for c in new_customers:
            suffix = f" ({c['annotation']})" if c['annotation'] else ''
            print(f"    [DRY RUN] Would create: {c['display_name']} [{c['cohort']}]{suffix}")
        created = len(new_customers)

    # Summary
    print(f"\n{'=' * 60}")
    print(f"  Summary:")
    print(f"    Placeholders archived: {len(placeholder_pages)}")
    print(f"    Customers created: {created}")
    print(f"    Customers skipped: {len(skipped)}")
    print(f"    Total in DB: {len(existing_names) - len(placeholder_pages) + created}")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    main()
