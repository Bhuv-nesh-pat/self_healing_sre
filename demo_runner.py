#!/usr/bin/env python3
"""
Autonomous AI SRE Incident Commander - Hackathon Live Demo Runner
=================================================================
A single-command interactive demonstration script for adjudicators and presenters.
Sequentially invokes the unstable microservice, seeds realistic error logs and metrics,
triggers the telemetry alert generator, and validates the autonomous incident response.
"""

import sys
import time
import json
import requests

MOCK_URL = "http://localhost:8000"
N8N_URL = "http://localhost:5678"
WEBHOOK_URL = f"{N8N_URL}/webhook/sre-incident-alert"

BOLD = "\033[1m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RESET = "\033[0m"

def print_banner():
    print(f"""
{CYAN}{BOLD}================================================================================
   AUTONOMOUS AI SRE INCIDENT COMMANDER — LIVE ADJUDICATION RUNNER
================================================================================{RESET}
""")

def step(title):
    print(f"\n{BOLD}{CYAN}>>> [STEP] {title}{RESET}")

def success(msg):
    print(f"    {GREEN}✔ {msg}{RESET}")

def warn(msg):
    print(f"    {YELLOW}▲ {msg}{RESET}")

def error(msg):
    print(f"    {RED}✖ {msg}{RESET}")

def wait_for_services():
    step("Verifying Environment Health...")
    
    # Check Mock Service
    try:
        r = requests.get(f"{MOCK_URL}/health", timeout=3)
        if r.status_code == 200:
            success(f"Mock Microservice is ONLINE: {r.json().get('service')} ({r.json().get('version')})")
        else:
            warn(f"Mock Microservice returned unexpected status: {r.status_code}")
    except requests.RequestException:
        error(f"Cannot reach Mock Microservice at {MOCK_URL}. Did you run 'docker compose up -d'?")
        sys.exit(1)

    # Check n8n
    try:
        r = requests.get(f"{N8N_URL}/healthz", timeout=3)
        if r.status_code == 200:
            success(f"n8n Orchestration Engine is ONLINE at {N8N_URL}")
        else:
            success(f"n8n Orchestration Engine reachable at {N8N_URL}")
    except requests.RequestException:
        warn(f"n8n is not reachable at {N8N_URL}. Ensure container 'sre-n8n-commander' is running.")

def seed_failures():
    step("Simulating Production Anomaly: Seeding Erratic Transactions & Container Logs...")
    print("    Emitting 10 high-concurrency transactions with chaos injections...")
    
    success_count = 0
    failure_count = 0

    for i in range(1, 11):
        try:
            # Force occasional explicit errors to guarantee threshold breach
            force_type = "npe" if i in (2, 5, 8) else None
            resp = requests.post(
                f"{MOCK_URL}/api/v1/process-transaction",
                json={"account_id": f"act_00{i}", "amount": 250.00, "currency": "USD"},
                params={"force_error": force_type} if force_type else {},
                timeout=4
            )
            if resp.status_code == 200:
                success_count += 1
                print(f"      Tx #{i:02d}: {GREEN}200 OK (Completed){RESET}")
            else:
                failure_count += 1
                err_data = resp.json()
                print(f"      Tx #{i:02d}: {RED}500 InternalServerError - {err_data.get('error_type')}{RESET}")
        except Exception as e:
            failure_count += 1
            print(f"      Tx #{i:02d}: {RED}Exception - {e}{RESET}")
        time.sleep(0.3)

    print(f"\n    Transaction Batch Completed: {GREEN}{success_count} Successes{RESET} | {RED}{failure_count} Failures{RESET}")

def inspect_metrics_and_logs():
    step("Validating Forensic Telemetry & Rolling Container Logs...")
    
    # Scrape Metrics
    try:
        r = requests.get(f"{MOCK_URL}/metrics", timeout=3)
        for line in r.text.splitlines():
            if "recent_error_rate_percent" in line and not line.startswith("#"):
                success(f"Prometheus Gauge 'recent_error_rate_percent': {BOLD}{line.split()[-1]}%{RESET}")
            if "simulated_exceptions_total" in line and not line.startswith("#"):
                success(f"Prometheus Counter 'simulated_exceptions_total': {line}")
    except Exception as e:
        warn(f"Could not read metrics: {e}")

    # Inspect Logs
    try:
        r = requests.get(f"{MOCK_URL}/logs?limit=3", timeout=3)
        logs = r.json().get("logs", [])
        success(f"Forensic Rolling Buffer contains {r.json().get('total_buffered')} structured events.")
        if logs:
            print(f"    {BOLD}Latest Exception Captured in Forensic Buffer:{RESET}")
            latest_err = logs[-1]
            print(f"      Timestamp: {latest_err.get('timestamp')}")
            print(f"      Exception: {RED}{latest_err.get('exception_type')}: {latest_err.get('exception_message')}{RESET}")
    except Exception as e:
        warn(f"Could not read forensic logs: {e}")

def trigger_alert_webhook():
    step("Triggering Autonomous Incident Response via Webhook...")
    
   payload = {
        "status": "firing",
        "severity": "critical",
        "service_name": "mock-transaction-service",
        "error_signature": "Null reference in process_transaction function inside mock_service.py",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "telemetry_source": "AdjudicationDemoRunner"
    }

    print(f"    Dispatching HTTP POST to: {WEBHOOK_URL}")
    print(f"    Payload:\n{json.dumps(payload, indent=6)}")
    
    try:
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=5)
        if resp.status_code in (200, 202):
            success(f"Received Asynchronous Acknowledgment [{resp.status_code}]:")
            print(f"      {resp.text}")
            print(f"\n{BOLD}{GREEN}>>> SUCCESS! Autonomous SRE Incident Commander has taken control.{RESET}")
            print(f"""
{CYAN}{BOLD}What happens next (Autonomous Workflow Pipeline):{RESET}
 1. [Respond to Webhook] Returned HTTP 202 immediately (mitigating reverse-proxy timeout).
 2. [Fetch Forensic Context] Ingests container logs from mock service and git diff from GitHub.
 3. [AI SRE Agent] GPT-4o analyzes stack trace against Git diff with strict JSON Schema output.
 4. [Conditional Routing] Decision branch evaluated (DRAFT_HOTFIX or TRIGGER_ROLLBACK).
 5. [Remediation & HITL] Pull request drafted on GitHub and rich Post-Mortem published to Slack!

{BOLD}Check your n8n execution canvas at:{RESET} http://localhost:5678
""")
        else:
            warn(f"Webhook responded with status {resp.status_code}: {resp.text}")
            print("Note: If the webhook is not yet active, activate the 'Self-Healing SRE Incident Commander' workflow in the n8n UI.")
    except Exception as e:
        error(f"Failed to post to webhook: {e}")
        print(f"Make sure n8n is running and the workflow webhook is activated at {WEBHOOK_URL}.")

if __name__ == "__main__":
    print_banner()
    wait_for_services()
    seed_failures()
    inspect_metrics_and_logs()
    trigger_alert_webhook()
