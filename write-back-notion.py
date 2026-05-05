"""
Write computed fields back to Notion Implementation Console DB.

Reads implementation-data.json and writes:
  Status, Current Stage, Days in Stage, Health, Next Action,
  Calls (30d), Deflection Rate, CSAT, Last Synced

Usage:
    python implementation-console/write-back-notion.py [--dry-run]
"""

import json
import os
import sys
import time
import requests
from datetime import datetime, date
from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, 'data')

NOTION_API_KEY = os.environ.get('NOTION_API_KEY')
if not NOTION_API_KEY:
    print("ERROR: NOTION_API_KEY not found in .env")
    sys.exit(1)

HEADERS = {
    'Authorization': f'Bearer {NOTION_API_KEY}',
    'Content-Type': 'application/json',
    'Notion-Version': '2022-06-28',
}

RATE_LIMIT_DELAY = 0.5


def notion_request(method, url, json_body=None):
    time.sleep(RATE_LIMIT_DELAY)
    for attempt in range(3):
        try:
            resp = requests.request(method, url, headers=HEADERS, json=json_body, timeout=30)
            if resp.status_code in (200, 201):
                return resp.json()
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = 2 ** attempt
                print(f"  WARN: {resp.status_code} -- retrying in {wait}s")
                time.sleep(wait)
                continue
            print(f"  ERROR: {resp.status_code}: {resp.text[:300]}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"  WARN: {e} -- retrying")
            time.sleep(2 ** attempt)
    return None


def update_page(page_id, properties):
    url = f'https://api.notion.com/v1/pages/{page_id}'
    return notion_request('PATCH', url, {'properties': properties})


def build_update_properties(c):
    """Build Notion property update payload from computed fields."""
    props = {}

    # Status (select)
    if c.get('computed_status'):
        props['Status'] = {'select': {'name': c['computed_status']}}

    # Current Stage (select)
    if c.get('computed_stage'):
        props['Current Stage'] = {'select': {'name': c['computed_stage']}}

    # Days in Stage (number)
    if c.get('computed_days_in_stage') is not None:
        props['Days in Stage'] = {'number': c['computed_days_in_stage']}

    # Health (select)
    if c.get('computed_health'):
        props['Health'] = {'select': {'name': c['computed_health']}}

    # Next Action (rich text)
    if c.get('computed_next_action'):
        props['Next Action'] = {
            'rich_text': [{'text': {'content': c['computed_next_action'][:2000]}}]
        }
    else:
        props['Next Action'] = {'rich_text': []}

    # Calls (30d) (number)
    if c.get('calls_30d') is not None:
        props['Calls (30d)'] = {'number': c['calls_30d']}

    # Deflection Rate (rich text)
    if c.get('deflection_rate'):
        val = c['deflection_rate']
        if isinstance(val, (int, float)):
            val = f"{val:.1f}%"
        props['Deflection Rate'] = {
            'rich_text': [{'text': {'content': str(val)}}]
        }

    # CSAT (number)
    if c.get('csat') is not None:
        props['CSAT'] = {'number': c['csat']}

    # Last Synced (date)
    props['Last Synced'] = {
        'date': {'start': datetime.now().isoformat()[:19]}
    }

    return props


def main():
    dry_run = '--dry-run' in sys.argv

    print("=" * 60)
    print("HOAi Implementation Console -- Write-Back to Notion")
    print(f"  Date: {date.today().isoformat()}")
    print(f"  Dry run: {dry_run}")
    print("=" * 60)

    # Load implementation data
    data_path = os.path.join(DATA_DIR, 'implementation-data.json')
    if not os.path.exists(data_path):
        print(f"  ERROR: {data_path} not found. Run fetch-implementation-data.py first.")
        sys.exit(1)

    with open(data_path) as f:
        data = json.load(f)

    customers = data.get('customers', [])
    print(f"\n  Customers to update: {len(customers)}")

    updated = 0
    failed = 0

    for c in customers:
        page_id = c.get('page_id')
        name = c.get('company_name', '?')

        if not page_id:
            print(f"    [FAIL] {name}: no page_id")
            failed += 1
            continue

        props = build_update_properties(c)

        if dry_run:
            print(f"    [DRY RUN] {name}: "
                  f"Status={c.get('computed_status')}, "
                  f"Stage={c.get('computed_stage')}, "
                  f"Health={c.get('computed_health')}, "
                  f"Days={c.get('computed_days_in_stage')}")
            updated += 1
            continue

        result = update_page(page_id, props)
        if result:
            print(f"    [OK] {name}: "
                  f"{c.get('computed_status')} / {c.get('computed_stage')} / "
                  f"{c.get('computed_health')} / {c.get('computed_days_in_stage')}d")
            updated += 1
        else:
            print(f"    [FAIL] {name}: update failed")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"  Updated: {updated}")
    print(f"  Failed: {failed}")
    print(f"{'=' * 60}")


if __name__ == '__main__':
    main()
