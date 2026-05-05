"""
Fetch implementation data from Notion + enrich from Supabase.

Usage:
    python implementation-console/fetch-implementation-data.py

Output:
    implementation-console/data/implementation-data.json
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
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(SCRIPT_DIR, 'data')
os.makedirs(DATA_DIR, exist_ok=True)

with open(os.path.join(SCRIPT_DIR, 'implementation-config.json')) as f:
    CONFIG = json.load(f)

NOTION_API_KEY = os.environ.get('NOTION_API_KEY')
if not NOTION_API_KEY:
    print("ERROR: NOTION_API_KEY not found in .env")
    sys.exit(1)

DATABASE_ID = CONFIG['notion']['database_id']
RATE_LIMIT_DELAY = 0.5

HEADERS = {
    'Authorization': f'Bearer {NOTION_API_KEY}',
    'Content-Type': 'application/json',
    'Notion-Version': '2022-06-28',
}


# -- Notion API --------------------------------------------------------------
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


def query_all_pages():
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


# -- Property Extractors ----------------------------------------------------─
def get_title(props, name):
    arr = props.get(name, {}).get('title', [])
    return arr[0].get('text', {}).get('content', '') if arr else ''


def get_date(props, name):
    d = props.get(name, {}).get('date')
    return d.get('start') if d else None


def get_checkbox(props, name):
    return props.get(name, {}).get('checkbox', False)


def get_select(props, name):
    s = props.get(name, {}).get('select')
    return s.get('name') if s else None


def get_rich_text(props, name):
    arr = props.get(name, {}).get('rich_text', [])
    return arr[0].get('text', {}).get('content', '') if arr else ''


def get_number(props, name):
    return props.get(name, {}).get('number')


# -- Stage Computation --------------------------------------------------------
def compute_current_stage(c):
    """Determine current stage -- find the furthest completed milestone,
    then return the next one as the current working stage.

    Milestones are checked in reverse order (latest first). The first
    completed milestone tells us where the customer is. This handles
    cases where earlier dates (e.g. welcome_package_date) aren't filled in.
    """
    today = date.today().isoformat()

    # Check completion from latest to earliest
    if c['live_testing_complete']:
        return 'Activation'
    if c['customer_testing_complete']:
        return 'Live Testing'
    if c['hoai_testing_complete']:
        return 'Customer Testing'
    # Alignment call happened (date is in the past)
    if c['alignment_call_date'] and c['alignment_call_date'] <= today:
        return 'HOAi Testing'
    # Alignment call scheduled but still in the future
    if c['alignment_call_date'] and c['alignment_call_date'] > today:
        return 'Alignment Call'
    if c['aop_config']:
        return 'Alignment Call'
    if c['questionnaire_complete']:
        return 'AOP Configuration'
    if c['welcome_package_date']:
        return 'Questionnaire'
    return 'Welcome Package'


def compute_stage_entry_date(c, stage):
    """When did the customer enter this stage?"""
    date_map = {
        'Welcome Package': c['welcome_package_date'],
        'Questionnaire': c['welcome_package_date'],
        'AOP Configuration': c['welcome_package_date'],
        'Alignment Call': c['alignment_call_date'] or c['welcome_package_date'],
        'HOAi Testing': c['hoai_testing_date'] or c['alignment_call_date'],
        'Customer Testing': c['customer_testing_date'] or c['hoai_testing_date'],
        'Live Testing': c['live_testing_date'] or c['customer_testing_date'],
        'Activation': c['activation_date'] or c['live_testing_date'],
    }
    return date_map.get(stage)


def compute_days_in_stage(entry_date_str):
    if not entry_date_str:
        return 0
    try:
        entry = datetime.strptime(entry_date_str, '%Y-%m-%d').date()
        return max(0, (date.today() - entry).days)
    except ValueError:
        return 0


def compute_health(days_in_stage, stage):
    """Green / Amber / Red based on days in stage and stale threshold."""
    threshold = CONFIG['thresholds']['stale_days']  # 7
    if stage == 'Activation':
        return 'Green'
    if days_in_stage > threshold:
        return 'Red'
    if days_in_stage > threshold - 2:
        return 'Amber'
    return 'Green'


def compute_status(c, health):
    stage = c.get('computed_stage', 'Welcome Package')
    if stage == 'Activation':
        return 'Complete'
    if health == 'Red':
        return 'Stalled'
    if c['welcome_package_date'] or c['questionnaire_complete'] or c['aop_config']:
        return 'In Progress'
    return 'Not Started'


def compute_next_action(c, stage):
    """Suggest the next action based on current stage."""
    name = c['company_name']
    if stage == 'Welcome Package' and not c['welcome_package_date']:
        return f'Set Welcome Package date for {name}'
    if stage == 'Welcome Package' and not c['questionnaire_complete']:
        return f'Waiting on questionnaire -- follow up with {name}'
    if stage == 'Questionnaire' and not c['aop_config']:
        return f'/generate-aop {name}'
    if stage == 'AOP Configuration' and not c['alignment_call_date']:
        return f'Schedule alignment call for {name}'
    if stage == 'Alignment Call' and not c['hoai_testing_date']:
        return f'Set HOAi Internal Testing date for {name}'
    if stage == 'HOAi Testing' and not c['hoai_testing_complete']:
        return f'Waiting on HOAi testing -- /analyze-calls {name}'
    if stage == 'Customer Testing' and not c['customer_testing_complete']:
        return f'Waiting on customer testing -- /analyze-calls {name}'
    if stage == 'Live Testing' and not c['live_testing_complete']:
        return f'Waiting on live testing -- /analyze-calls {name}'
    if stage == 'Activation':
        return 'Go-live complete'
    return ''


# -- Supabase Enrichment ----------------------------------------------------─
def enrich_with_supabase(customers):
    """Add call metrics from Supabase for each customer."""
    sys.path.insert(0, ROOT_DIR)
    try:
        from supabase.queries.call_logs import get_summary
        from supabase.queries.management_companies import find_by_name
    except ImportError:
        print("  WARN: Could not import supabase queries -- skipping enrichment")
        return

    today = date.today().isoformat()
    thirty_days_ago = (date.today().replace(day=1)).isoformat()  # approx

    for c in customers:
        try:
            matches = find_by_name(c['company_name'])
            if not matches:
                continue
            company_name = matches[0]['name']
            summary = get_summary(company_name, thirty_days_ago, today)
            if summary:
                c['calls_30d'] = summary.get('total_calls', 0)
                c['deflection_rate'] = summary.get('deflection_rate', '')
                c['csat'] = summary.get('avg_csat')
        except Exception as e:
            print(f"  WARN: Supabase enrichment failed for {c['company_name']}: {e}")


# -- Main --------------------------------------------------------------------─
def main():
    print("=" * 60)
    print("HOAi Implementation Console -- Fetch Data")
    print(f"  Date: {date.today().isoformat()}")
    print("=" * 60)

    # 1. Query Notion
    print("\n  Querying Notion DB...")
    pages = query_all_pages()
    print(f"  Found {len(pages)} pages")

    # 2. Parse into structured data
    customers = []
    for page in pages:
        props = page.get('properties', {})
        company_name = get_title(props, 'Company Name')
        if not company_name or company_name.startswith('Item '):
            continue

        c = {
            'page_id': page['id'],
            'company_name': company_name,
            'notion_url': page.get('url', ''),
            # Dates
            'welcome_package_date': get_date(props, 'Welcome Package'),
            'alignment_call_date': get_date(props, 'Alignment Call'),
            'hoai_testing_date': get_date(props, 'HOAi Internal Testing'),
            'customer_testing_date': get_date(props, 'Customer Internal Testing'),
            'live_testing_date': get_date(props, 'Live Testing Date'),
            'activation_date': get_date(props, 'Activation Date'),
            # Checkboxes
            'questionnaire_complete': get_checkbox(props, 'Questionnaire Complete'),
            'aop_config': get_checkbox(props, 'AOP Configuration'),
            'hoai_testing_complete': get_checkbox(props, 'HOAi Testing Complete?'),
            'customer_testing_complete': get_checkbox(props, 'Customer Testing Complete?'),
            'live_testing_complete': get_checkbox(props, 'Live Testing Complete'),
            # Selects
            'fde': get_select(props, 'FDE'),
            'priority': get_select(props, 'Priority'),
            'status': get_select(props, 'Status'),
            'health': get_select(props, 'Health'),
            'current_stage': get_select(props, 'Current Stage'),
            # Text
            'cohort': get_rich_text(props, 'Cohort'),
            'implementation_notes': get_rich_text(props, 'Implementation Notes'),
            'next_action': get_rich_text(props, 'Next Action'),
            # Metrics (will be enriched from Supabase)
            'calls_30d': get_number(props, 'Calls (30d)'),
            'deflection_rate': get_rich_text(props, 'Deflection Rate'),
            'csat': get_number(props, 'CSAT'),
            # Planned dates (for Budget vs Actual)
            'planned_welcome_package': get_date(props, 'Planned Welcome Package'),
            'planned_questionnaire': get_date(props, 'Planned Questionnaire'),
            'planned_aop': get_date(props, 'Planned AOP Configuration'),
            'planned_alignment_call': get_date(props, 'Planned Alignment Call'),
            'planned_hoai_testing': get_date(props, 'Planned HOAi Internal Testing'),
            'planned_customer_testing': get_date(props, 'Planned Customer Internal Testing'),
            'planned_live_testing': get_date(props, 'Planned Live Testing'),
            'planned_activation': get_date(props, 'Planned Activation'),
            # Extra fields for dashboard
            'base_fde': get_select(props, 'Base FDE'),
            'voice_fde': get_select(props, 'Voice FDE'),
            'delay_reason': get_rich_text(props, 'Delay Reason'),
            'main_overflow': get_select(props, 'Main Line or Overflow'),
            'calls_enabled': get_checkbox(props, 'Calls Enabled'),
            'sms_enabled': get_checkbox(props, 'SMS Enabled'),
            'webchat_enabled': get_checkbox(props, 'Webchat Enabled'),
        }

        # Compute derived fields
        c['computed_stage'] = compute_current_stage(c)
        entry_date = compute_stage_entry_date(c, c['computed_stage'])
        c['computed_days_in_stage'] = compute_days_in_stage(entry_date)
        c['computed_health'] = compute_health(c['computed_days_in_stage'], c['computed_stage'])
        c['computed_status'] = compute_status(c, c['computed_health'])
        c['computed_next_action'] = compute_next_action(c, c['computed_stage'])

        customers.append(c)

    print(f"  Parsed {len(customers)} customers")
    for c in customers:
        print(f"    - {c['company_name']} [{c['computed_stage']}] "
              f"({c['computed_status']}, {c['computed_health']})")

    # 3. Enrich with Supabase metrics
    print("\n  Enriching with Supabase metrics...")
    enrich_with_supabase(customers)

    # 4. Write output
    output = {
        'generated_at': datetime.now().isoformat(),
        'date': date.today().isoformat(),
        'customer_count': len(customers),
        'customers': customers,
    }

    output_path = os.path.join(DATA_DIR, 'implementation-data.json')
    with open(output_path, 'w') as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\n  Written to {output_path}")

    # 5. Summary
    stages = {}
    for c in customers:
        s = c['computed_stage']
        stages[s] = stages.get(s, 0) + 1

    print(f"\n  Pipeline summary:")
    for stage, count in sorted(stages.items()):
        print(f"    {stage}: {count}")

    stalled = [c for c in customers if c['computed_health'] == 'Red']
    if stalled:
        print(f"\n  Stalled ({len(stalled)}):")
        for c in stalled:
            print(f"    [WARN] {c['company_name']} -- {c['computed_days_in_stage']}d in {c['computed_stage']}")

    print(f"\n{'=' * 60}")


if __name__ == '__main__':
    main()
