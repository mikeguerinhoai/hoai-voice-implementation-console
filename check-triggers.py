"""
Implementation Console Trigger Engine.

Morning mode (default):
    - Reads implementation-data.json
    - Diffs against notion-state.json to detect changes
    - Evaluates forward-looking triggers (T1-T4, T6-T7, T9, T11-T13)
    - Generates deliverables (welcome drafts, deck reminders)
    - Posts to Teams
    - Saves state for next run

Evening mode (--analyze-only):
    - Reads implementation-data.json (no re-fetch)
    - Checks if testing analyses are due TODAY
    - Executes /analyze-calls and /action-review
    - Posts results to Teams + Notion

Usage:
    python implementation-console/check-triggers.py
    python implementation-console/check-triggers.py --analyze-only
    python implementation-console/check-triggers.py --dry-run
"""

import glob as glob_mod
import json
import os
import sys
import subprocess
import time
from datetime import datetime, date, timedelta
from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
DATA_DIR = os.path.join(SCRIPT_DIR, 'data')

with open(os.path.join(SCRIPT_DIR, 'implementation-config.json')) as f:
    CONFIG = json.load(f)

TODAY = date.today().isoformat()
THRESHOLDS = CONFIG['thresholds']
FDE_EMAILS = CONFIG.get('fde_emails', {})

TEAMS_NOTIFY_JS = os.path.join(SCRIPT_DIR, 'teams-notify.js')


def resolve_fde_email(fde_name):
    """Resolve FDE name to email via config lookup."""
    return FDE_EMAILS.get(fde_name, None)


def send_teams_notification(card_type, data):
    """Send a Teams notification via teams-notify.js CLI."""
    try:
        result = subprocess.run(
            ['node', TEAMS_NOTIFY_JS, '--card-type', card_type, '--data', json.dumps(data, default=str)],
            capture_output=True, text=True, timeout=15, cwd=ROOT_DIR,
        )
        if result.returncode == 0:
            print(f"    [OK] Teams: {card_type} sent")
        else:
            print(f"    [FAIL] Teams: {card_type} failed -- {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        print(f"    [FAIL] Teams: {card_type} timed out")
    except Exception as e:
        print(f"    [FAIL] Teams: {card_type} error -- {e}")


# -- State Management ---------------------------------------------------------
def load_state():
    path = os.path.join(DATA_DIR, 'notion-state.json')
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {'customers': {}, 'last_run': None}


def save_state(state):
    state['last_run'] = datetime.now().isoformat()
    path = os.path.join(DATA_DIR, 'notion-state.json')
    with open(path, 'w') as f:
        json.dump(state, f, indent=2, default=str)


def load_trigger_log():
    path = os.path.join(DATA_DIR, 'trigger-actions.json')
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {'actions': []}


def save_trigger_log(log):
    path = os.path.join(DATA_DIR, 'trigger-actions.json')
    with open(path, 'w') as f:
        json.dump(log, f, indent=2, default=str)


def log_action(trigger_log, trigger_id, customer_name, action, mode):
    trigger_log['actions'].append({
        'timestamp': datetime.now().isoformat(),
        'trigger': trigger_id,
        'customer': customer_name,
        'action': action,
        'mode': mode,
    })


# -- Date Helpers -------------------------------------------------------------
def days_until(date_str):
    if not date_str:
        return None
    try:
        target = datetime.strptime(date_str, '%Y-%m-%d').date()
        return (target - date.today()).days
    except ValueError:
        return None


def is_today_or_tomorrow(date_str):
    d = days_until(date_str)
    return d is not None and d in (0, 1)


def is_today(date_str):
    return date_str == TODAY


def is_within_days(date_str, n):
    d = days_until(date_str)
    return d is not None and 0 <= d <= n


# -- Change Detection ---------------------------------------------------------
def detect_changes(customer, prev_state):
    """Compare current customer state to previous state, return list of changes."""
    changes = []
    name = customer['company_name']
    prev = prev_state.get('customers', {}).get(name, {})

    # Check checkbox transitions (False -> True)
    checkbox_fields = [
        ('questionnaire_complete', 'Questionnaire Complete'),
        ('aop_config', 'AOP Configuration'),
        ('hoai_testing_complete', 'HOAi Testing Complete'),
        ('customer_testing_complete', 'Customer Testing Complete'),
        ('live_testing_complete', 'Live Testing Complete'),
    ]
    for field, display in checkbox_fields:
        if customer.get(field) and not prev.get(field):
            changes.append(f'{display} just checked')

    # Check date fields (None -> set)
    date_fields = [
        ('welcome_package_date', 'Welcome Package'),
        ('alignment_call_date', 'Alignment Call'),
        ('hoai_testing_date', 'HOAi Internal Testing'),
        ('customer_testing_date', 'Customer Internal Testing'),
        ('live_testing_date', 'Live Testing Date'),
        ('activation_date', 'Activation Date'),
    ]
    for field, display in date_fields:
        if customer.get(field) and not prev.get(field):
            changes.append(f'{display} date set to {customer[field]}')

    return changes


def snapshot_customer(customer):
    """Create a snapshot of trigger-relevant fields."""
    return {
        'welcome_package_date': customer.get('welcome_package_date'),
        'alignment_call_date': customer.get('alignment_call_date'),
        'hoai_testing_date': customer.get('hoai_testing_date'),
        'customer_testing_date': customer.get('customer_testing_date'),
        'live_testing_date': customer.get('live_testing_date'),
        'activation_date': customer.get('activation_date'),
        'questionnaire_complete': customer.get('questionnaire_complete'),
        'aop_config': customer.get('aop_config'),
        'hoai_testing_complete': customer.get('hoai_testing_complete'),
        'customer_testing_complete': customer.get('customer_testing_complete'),
        'live_testing_complete': customer.get('live_testing_complete'),
    }


# -- Trigger Evaluation ------------------------------------------------------
def evaluate_morning_triggers(customers, prev_state, trigger_log, dry_run):
    """Evaluate all morning triggers. Returns list of actions taken."""
    actions = []

    for c in customers:
        name = c['company_name']
        changes = detect_changes(c, prev_state)

        if changes:
            print(f"\n  Changes detected for {name}:")
            for ch in changes:
                print(f"    -> {ch}")

        # T1: Welcome Package is today/tomorrow
        if is_today_or_tomorrow(c.get('welcome_package_date')):
            d = days_until(c['welcome_package_date'])
            label = 'today' if d == 0 else 'tomorrow'
            print(f"\n  [T1] Welcome Package {label} -- {name}")
            if not dry_run:
                generate_welcome_package(c)
            actions.append({'trigger': 'T1', 'customer': name, 'action': f'Welcome Package draft ({label})', 'mode': 'AUTO'})
            log_action(trigger_log, 'T1', name, f'Welcome Package draft ({label})', 'AUTO')
            if not dry_run:
                send_teams_notification('welcome', {
                    'customer': name, 'fde': c.get('fde', ''),
                    'go_live_date': c.get('activation_date', ''), 'notion_url': c.get('notion_url', ''),
                })

        # T2: Questionnaire checked + Alignment in 7d + no AOP
        if (c.get('questionnaire_complete')
                and not c.get('aop_config')
                and is_within_days(c.get('alignment_call_date'), THRESHOLDS['aop_reminder_days'])):
            d = days_until(c['alignment_call_date'])
            print(f"\n  [T2] AOP needed -- {name} (alignment in {d}d)")
            actions.append({'trigger': 'T2', 'customer': name, 'action': f'AOP reminder (alignment in {d}d)', 'mode': 'SUGGEST'})
            log_action(trigger_log, 'T2', name, f'Suggest /generate-aop', 'SUGGEST')
            if not dry_run:
                send_teams_notification('aop_reminder', {
                    'customer': name, 'fde': c.get('fde', ''),
                    'days_to_alignment': d, 'notion_url': c.get('notion_url', ''),
                })

        # T3: Alignment Call in 2 days + no deck (skip if already generated this cycle)
        t3_already_fired = any(
            a['trigger'] == 'T3' and a['customer'] == name
            for a in trigger_log.get('actions', [])
        )
        if (is_within_days(c.get('alignment_call_date'), THRESHOLDS['deck_lead_days'])
                and not t3_already_fired):
            d = days_until(c['alignment_call_date'])
            if d is not None and d >= 0:
                print(f"\n  [T3] Alignment deck needed -- {name} (call in {d}d)")
                actions.append({'trigger': 'T3', 'customer': name, 'action': f'Generate alignment deck (call in {d}d)', 'mode': 'AUTO'})
                log_action(trigger_log, 'T3', name, f'Generate alignment deck', 'AUTO')
                if not dry_run:
                    deck_path = generate_alignment_deck(c)
                    send_teams_notification('deck_ready', {
                        'customer': name, 'fde': c.get('fde', ''),
                        'alignment_date': c.get('alignment_call_date', ''),
                        'days_away': d, 'deck_path': deck_path or 'Generation failed',
                        'notion_url': c.get('notion_url', ''),
                    })

        # T4: AOP Configuration just checked
        if 'AOP Configuration just checked' in changes:
            print(f"\n  [T4] AOP complete -- {name}")
            actions.append({'trigger': 'T4', 'customer': name, 'action': 'AOP complete confirmation', 'mode': 'INFO'})
            log_action(trigger_log, 'T4', name, 'AOP complete', 'INFO')

        # T6: HOAi Testing Complete just checked
        if 'HOAi Testing Complete just checked' in changes:
            print(f"\n  [T6] HOAi testing complete -- {name}")
            actions.append({'trigger': 'T6', 'customer': name, 'action': 'Suggest scheduling customer testing', 'mode': 'SUGGEST'})
            log_action(trigger_log, 'T6', name, 'Suggest customer testing', 'SUGGEST')

        # T7: Customer Testing date + 3 days (check-in reminder)
        if c.get('customer_testing_date') and not c.get('customer_testing_complete'):
            d = days_until(c['customer_testing_date'])
            if d is not None and d == -THRESHOLDS['checkin_days_after_customer_testing']:
                print(f"\n  [T7] Customer testing check-in -- {name} ({abs(d)}d since testing)")
                actions.append({'trigger': 'T7', 'customer': name, 'action': 'Customer testing check-in', 'mode': 'SUGGEST'})
                log_action(trigger_log, 'T7', name, 'Check-in reminder', 'SUGGEST')

        # T9: Customer Testing Complete just checked
        if 'Customer Testing Complete just checked' in changes:
            print(f"\n  [T9] Customer testing complete -- {name}")
            actions.append({'trigger': 'T9', 'customer': name, 'action': 'Suggest scheduling live testing', 'mode': 'SUGGEST'})
            log_action(trigger_log, 'T9', name, 'Suggest live testing', 'SUGGEST')

        # T11: Live Testing Complete just checked
        if 'Live Testing Complete just checked' in changes:
            print(f"\n  [T11] Live testing complete -- {name}")
            actions.append({'trigger': 'T11', 'customer': name, 'action': 'Suggest activation', 'mode': 'SUGGEST'})
            log_action(trigger_log, 'T11', name, 'Suggest activation', 'SUGGEST')

        # T12: Stalled > 7 days
        if c.get('computed_days_in_stage', 0) > THRESHOLDS['stale_days']:
            if c.get('computed_stage') != 'Activation':
                print(f"\n  [T12] STALLED -- {name} ({c['computed_days_in_stage']}d in {c['computed_stage']})")
                actions.append({
                    'trigger': 'T12', 'customer': name,
                    'action': f"Stalled {c['computed_days_in_stage']}d in {c['computed_stage']}",
                    'mode': 'ALERT',
                    'stage': c.get('computed_stage', ''),
                    'days_in_stage': c.get('computed_days_in_stage', 0),
                })
                log_action(trigger_log, 'T12', name, f"Stalled {c['computed_days_in_stage']}d in {c['computed_stage']}", 'ALERT')
                if not dry_run:
                    send_teams_notification('stalled', {
                        'customer': name, 'stage': c.get('computed_stage', ''),
                        'days_in_stage': c.get('computed_days_in_stage', 0),
                        'fde': c.get('fde', ''),
                        'suggested_action': f"Follow up -- no progress in {c['computed_stage']} for {c['computed_days_in_stage']} days",
                        'notion_url': c.get('notion_url', ''),
                    })

    return actions


def evaluate_evening_triggers(customers, trigger_log, dry_run):
    """Evaluate evening analysis triggers. Returns list of actions taken."""
    actions = []

    for c in customers:
        name = c['company_name']

        # T5: HOAi Internal Testing date = today
        if is_today(c.get('hoai_testing_date')) and not c.get('hoai_testing_complete'):
            print(f"\n  [T5] HOAi Testing analysis due -- {name}")
            if not dry_run:
                run_analysis(c, 'hoai_testing')
            actions.append({'trigger': 'T5', 'customer': name, 'action': '/analyze-calls (HOAi Testing)', 'mode': 'AUTO'})
            log_action(trigger_log, 'T5', name, 'HOAi Testing analysis', 'AUTO')

        # T8: Customer Internal Testing date = today
        if is_today(c.get('customer_testing_date')) and not c.get('customer_testing_complete'):
            print(f"\n  [T8] Customer Testing analysis due -- {name}")
            if not dry_run:
                run_analysis(c, 'customer_testing')
            actions.append({'trigger': 'T8', 'customer': name, 'action': '/analyze-calls (Customer Testing)', 'mode': 'AUTO'})
            log_action(trigger_log, 'T8', name, 'Customer Testing analysis', 'AUTO')

        # T10: Live Testing Date = today
        if is_today(c.get('live_testing_date')) and not c.get('live_testing_complete'):
            print(f"\n  [T10] Live Testing analysis due -- {name}")
            if not dry_run:
                run_analysis(c, 'live_testing')
                run_action_review(c)
            actions.append({'trigger': 'T10', 'customer': name, 'action': '/analyze-calls + /action-review (Live Testing)', 'mode': 'AUTO'})
            log_action(trigger_log, 'T10', name, 'Live Testing analysis + action review', 'AUTO')

    return actions


# -- Metric Extraction --------------------------------------------------------
def extract_analysis_metrics(report_path):
    """Extract top-line metrics from analysis output (JSON companion file)."""
    if not report_path:
        return None

    # Try JSON companion (same name, .json extension)
    json_path = report_path
    if report_path.endswith('.html'):
        json_path = report_path.replace('.html', '.json')

    full_path = os.path.join(ROOT_DIR, json_path) if not os.path.isabs(json_path) else json_path
    if not os.path.exists(full_path):
        return None

    try:
        with open(full_path) as f:
            data = json.load(f)
        metrics = {}
        if 'total_calls' in data:
            metrics['Total Calls'] = str(data['total_calls'])
        if 'deflection_rate' in data:
            metrics['Deflection Rate'] = f"{data['deflection_rate']}%"
        if 'csat' in data:
            metrics['CSAT'] = str(data['csat'])
        if 'resolution_rate' in data:
            metrics['Resolution Rate'] = f"{data['resolution_rate']}%"
        # Action review specific
        if 'total_items' in data:
            metrics['Total Items'] = str(data['total_items'])
        if 'completion_rate' in data:
            metrics['Completion Rate'] = f"{data['completion_rate']}%"
        return metrics if metrics else None
    except (json.JSONDecodeError, KeyError):
        return None


# -- Action Executors ---------------------------------------------------------
def generate_welcome_package(customer):
    """Call generate-welcome-package.js for this customer."""
    json_path = os.path.join(DATA_DIR, f'_tmp_welcome_{customer["company_name"].replace(" ", "_")}.json')
    with open(json_path, 'w') as f:
        json.dump(customer, f, default=str)

    cmd = ['node', os.path.join(SCRIPT_DIR, 'generate-welcome-package.js'),
           '--from-json', json_path, '--post-teams']
    print(f"    Running: {' '.join(cmd[:3])}...")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=ROOT_DIR)
        if result.returncode == 0:
            print(f"    [OK]Welcome package generated")
        else:
            print(f"    [FAIL]Welcome package failed: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        print(f"    [FAIL]Welcome package timed out")
    finally:
        if os.path.exists(json_path):
            os.remove(json_path)


def generate_alignment_deck(customer):
    """Generate alignment deck PPTX. Returns deck path on success, None on failure."""
    name = customer['company_name']
    go_live = customer.get('activation_date', '')

    if not go_live:
        print(f"    WARN: No activation_date for {name} -- cannot generate deck")
        return None

    gen_script = os.path.join(ROOT_DIR, 'alignment-deck', 'generate-alignment-deck.js')
    try:
        result = subprocess.run(
            ['node', gen_script, name, '--go-live', go_live],
            capture_output=True, text=True, timeout=90, cwd=ROOT_DIR,
        )
        if result.returncode == 0:
            print(f"    [OK]Alignment deck generated for {name}")
            # Extract output path from stdout if present
            for line in result.stdout.splitlines():
                if 'Alignment_Call_' in line or '.pptx' in line:
                    return line.strip()
            return f"alignment-deck/output/{name}"
        else:
            print(f"    [FAIL]Alignment deck failed: {result.stderr[:200]}")
            return None
    except subprocess.TimeoutExpired:
        print(f"    [FAIL]Alignment deck timed out")
        return None


def run_analysis(customer, phase):
    """Run call analysis for a customer. Invokes voice-functionality-analysis scripts directly."""
    name = customer['company_name']
    start_date = customer.get('welcome_package_date', '')
    end_date_map = {
        'hoai_testing': customer.get('hoai_testing_date', ''),
        'customer_testing': customer.get('customer_testing_date', ''),
        'live_testing': customer.get('live_testing_date', ''),
    }
    end_date = end_date_map.get(phase, '')

    if not start_date or not end_date:
        print(f"    WARN: Missing date range for {name} {phase} analysis")
        return

    phase_display = phase.replace('_', ' ').title()
    print(f"    Running call analysis: {name} ({phase_display}) {start_date} -> {end_date}")

    # Step 1: Fetch call analysis data
    fetch_script = os.path.join(ROOT_DIR, 'voice-functionality-analysis', 'fetch-call-analysis-data.py')
    try:
        result = subprocess.run(
            ['python', fetch_script, '--company', name, '--start', start_date, '--end', end_date],
            capture_output=True, text=True, timeout=120, cwd=ROOT_DIR,
        )
        if result.returncode != 0:
            print(f"    [FAIL]Fetch failed: {result.stderr[:200]}")
            return
        print(f"    [OK]Data fetched")
    except subprocess.TimeoutExpired:
        print(f"    [FAIL]Fetch timed out")
        return

    # Step 2: Generate HTML report
    gen_script = os.path.join(ROOT_DIR, 'voice-functionality-analysis', 'generate-call-analysis.js')
    try:
        result = subprocess.run(
            ['node', gen_script],
            capture_output=True, text=True, timeout=60, cwd=ROOT_DIR,
        )
        if result.returncode != 0:
            print(f"    [FAIL]Report generation failed: {result.stderr[:200]}")
            return
        print(f"    [OK]Report generated")
    except subprocess.TimeoutExpired:
        print(f"    [FAIL]Report generation timed out")
        return

    # Step 3: Extract metrics + Post to Teams
    slug = name.lower().replace(' ', '-').replace(',', '').replace('.', '')
    report_path = f"voice-functionality-analysis/output/{slug}/Call_Analysis_{start_date}_{end_date}.html"
    metrics = extract_analysis_metrics(report_path)
    send_teams_notification('analysis_result', {
        'customer': name, 'analysis_type': phase_display,
        'fde': customer.get('fde', ''),
        'report_path': report_path, 'notion_url': customer.get('notion_url', ''),
        'metrics': metrics or {},
    })


def run_action_review(customer):
    """Run action item review for a customer during live testing."""
    name = customer['company_name']
    start_date = customer.get('welcome_package_date', '')
    end_date = customer.get('live_testing_date', '')

    if not start_date or not end_date:
        print(f"    WARN: Missing date range for {name} action review")
        return

    print(f"    Running action review: {name} {start_date} -> {end_date}")

    # Step 1: Fetch and classify action items
    fetch_script = os.path.join(ROOT_DIR, 'action-review', 'fetch-action-review.py')
    try:
        result = subprocess.run(
            ['python', fetch_script, '--company', name, '--start', start_date, '--end', end_date],
            capture_output=True, text=True, timeout=120, cwd=ROOT_DIR,
        )
        if result.returncode != 0:
            print(f"    [FAIL]Action review fetch failed: {result.stderr[:200]}")
            return
        print(f"    [OK]Action review data fetched")
    except subprocess.TimeoutExpired:
        print(f"    [FAIL]Action review fetch timed out")
        return

    # Step 2: Generate HTML report
    slug = name.lower().replace(' ', '-').replace(',', '').replace('.', '')
    json_glob = os.path.join(ROOT_DIR, 'action-review', 'data', f'{slug}_action-review_*.json')
    json_files = sorted(glob_mod.glob(json_glob), reverse=True)
    if not json_files:
        print(f"    [FAIL]No action review JSON found for {name}")
        return

    gen_script = os.path.join(ROOT_DIR, 'action-review', 'generate-action-review.js')
    try:
        result = subprocess.run(
            ['node', gen_script, json_files[0]],
            capture_output=True, text=True, timeout=60, cwd=ROOT_DIR,
        )
        if result.returncode != 0:
            print(f"    [FAIL]Action review report failed: {result.stderr[:200]}")
            return
        print(f"    [OK]Action review report generated")
    except subprocess.TimeoutExpired:
        print(f"    [FAIL]Action review report timed out")
        return

    # Post to Teams
    metrics = extract_analysis_metrics(json_files[0])
    send_teams_notification('analysis_result', {
        'customer': name, 'analysis_type': 'Action Item Review',
        'fde': customer.get('fde', ''),
        'report_path': json_files[0], 'notion_url': customer.get('notion_url', ''),
        'metrics': metrics or {},
    })


# -- Morning Briefing ---------------------------------------------------------
def generate_briefing(customers, actions):
    """Generate morning briefing summary."""
    pipeline_count = len(customers)
    generated = [a for a in actions if a['mode'] == 'AUTO']
    stalled = [a for a in actions if a['trigger'] == 'T12']

    # Analyses due tonight
    analyses_tonight = []
    for c in customers:
        for phase, field in [('HOAi Testing', 'hoai_testing_date'),
                             ('Customer Testing', 'customer_testing_date'),
                             ('Live Testing', 'live_testing_date')]:
            if is_today(c.get(field)):
                analyses_tonight.append(f"{c['company_name']} ({phase})")

    # Due this week
    due_this_week = []
    for c in customers:
        for field_name, display in [('alignment_call_date', 'Alignment Call'),
                                     ('hoai_testing_date', 'HOAi Testing'),
                                     ('customer_testing_date', 'Customer Testing'),
                                     ('live_testing_date', 'Live Testing')]:
            d = days_until(c.get(field_name))
            if d is not None and 0 <= d <= 7:
                due_this_week.append(f"{c['company_name']}: {display} in {d}d")

    print(f"\n{'=' * 60}")
    print(f"  MORNING BRIEFING -- {TODAY}")
    print(f"{'=' * 60}")
    print(f"  Pipeline: {pipeline_count} active implementations")
    if generated:
        print(f"\n  Generated today ({len(generated)}):")
        for a in generated:
            print(f"    - {a['customer']}: {a['action']}")
    if analyses_tonight:
        print(f"\n  Analyses running tonight ({len(analyses_tonight)}):")
        for a in analyses_tonight:
            print(f"    - {a}")
    if due_this_week:
        print(f"\n  Due this week ({len(due_this_week)}):")
        for d in due_this_week:
            print(f"    - {d}")
    if stalled:
        print(f"\n  [WARN]Stalled ({len(stalled)}):")
        for a in stalled:
            print(f"    - {a['customer']}: {a['action']}")
    print(f"{'=' * 60}")

    return {
        'date': TODAY,
        'pipeline_count': pipeline_count,
        'generated_today': [a['action'] for a in generated],
        'analyses_tonight': analyses_tonight,
        'due_this_week': due_this_week,
        'stalled': [{'customer': a['customer'], 'detail': a['action']} for a in stalled],
    }


# -- Main ---------------------------------------------------------------------
def main():
    analyze_only = '--analyze-only' in sys.argv
    dry_run = '--dry-run' in sys.argv

    mode = 'EVENING (analysis-only)' if analyze_only else 'MORNING (full pipeline)'
    print("=" * 60)
    print(f"HOAi Implementation Console -- Trigger Engine [{mode}]")
    print(f"  Date: {TODAY}")
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
    print(f"\n  Loaded {len(customers)} customers from implementation data")

    # Load state + trigger log
    prev_state = load_state()
    trigger_log = load_trigger_log()

    if analyze_only:
        # Evening mode: only check analysis triggers
        print("\n  Checking evening analysis triggers...")
        actions = evaluate_evening_triggers(customers, trigger_log, dry_run)
        if not actions:
            print("  No analyses due today.")
    else:
        # Morning mode: evaluate all forward-looking triggers
        print("\n  Evaluating morning triggers...")
        actions = evaluate_morning_triggers(customers, prev_state, trigger_log, dry_run)

        # T13: Morning briefing (always)
        briefing = generate_briefing(customers, actions)
        if not dry_run:
            stalled_for_teams = [
                {'name': a['customer'], 'stage': a.get('stage', ''), 'days': a.get('days_in_stage', 0)}
                for a in actions if a['trigger'] == 'T12'
            ]
            send_teams_notification('morning_briefing', {
                'date': briefing['date'],
                'pipeline_count': briefing['pipeline_count'],
                'generated_today': len(briefing['generated_today']),
                'analyses_tonight': len(briefing['analyses_tonight']),
                'due_this_week': len(briefing['due_this_week']),
                'stalled_customers': stalled_for_teams,
            })

        # Update state snapshot
        new_state = {'customers': {}, 'last_run': datetime.now().isoformat()}
        for c in customers:
            new_state['customers'][c['company_name']] = snapshot_customer(c)

        if not dry_run:
            save_state(new_state)
            print("\n  [OK] State snapshot saved")

    # Save trigger log
    if not dry_run:
        save_trigger_log(trigger_log)
        print("  [OK] Trigger log saved")

    # Enrich implementation-data.json with trigger metadata for dashboard
    if not dry_run:
        data['last_trigger_run'] = datetime.now().isoformat()
        data['trigger_summary'] = {
            'fired': len(actions),
            'customers_checked': len(customers),
            'mode': 'evening' if analyze_only else 'morning'
        }
        all_actions = trigger_log.get('actions', [])
        for c in customers:
            name = c['company_name']
            c['trigger_history'] = [
                a for a in all_actions if a.get('customer') == name
            ]
        with open(data_path, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        print("  [OK] Implementation data enriched with trigger history")

    # Summary
    print(f"\n  Actions taken: {len(actions)}")
    for a in actions:
        print(f"    [{a['trigger']}] {a['customer']}: {a['action']} ({a['mode']})")


if __name__ == '__main__':
    main()
