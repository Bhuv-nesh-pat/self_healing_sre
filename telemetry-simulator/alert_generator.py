"""
Telemetry Event Simulator & Alert Generator
============================================
Acts as an autonomous SRE monitoring engine (proxying Prometheus Alertmanager / Datadog).
Continuously polls the mock microservice's /metrics endpoint, parses Prometheus exposition
format, detects threshold violations (error rate > 5%), and pushes simulated critical incident
webhook payloads to the n8n AI Incident Commander with exponential backoff.
"""

import os
import sys
import time
import json
import logging
import argparse
import threading
from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Configure standard logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [telemetry-simulator] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ"
)
logger = logging.getLogger("alert_generator")

# Environment configurations with robust fallbacks
MOCK_SERVICE_URL = os.getenv("MOCK_SERVICE_URL", "http://mock-microservice:8000").rstrip("/")
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "http://n8n:5678/webhook/sre-incident-alert")
POLL_INTERVAL_SECONDS = float(os.getenv("POLL_INTERVAL_SECONDS", "5.0"))
ERROR_THRESHOLD_PERCENT = float(os.getenv("ERROR_THRESHOLD_PERCENT", "5.0"))
ALERT_COOLDOWN_SECONDS = float(os.getenv("ALERT_COOLDOWN_SECONDS", "60.0"))
AUTO_GENERATE_TRAFFIC = os.getenv("AUTO_GENERATE_TRAFFIC", "true").lower() in ("true", "1", "yes")

def get_resilient_session(retries: int = 5, backoff_factor: float = 1.0) -> requests.Session:
    """
    Constructs a requests Session with HTTP retry adapter and exponential backoff
    for transient network connection failures and gateway timeouts.
    """
    session = requests.Session()
    retry_strategy = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST", "PUT"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

session = get_resilient_session()

def parse_prometheus_metrics(raw_text: str) -> Dict[str, Any]:
    """
    Parses Prometheus text exposition format into key-value metrics dictionary.
    Extracts gauge values and counter aggregates.
    """
    metrics: Dict[str, Any] = {
        "recent_error_rate_percent": None,
        "total_requests": 0.0,
        "failed_requests": 0.0,
        "simulated_exceptions": 0.0
    }

    for line in raw_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        if len(parts) < 2:
            continue

        metric_name_with_labels, value_str = parts[0], parts[1]
        try:
            val = float(value_str)
        except ValueError:
            continue

        if metric_name_with_labels.startswith("recent_error_rate_percent"):
            metrics["recent_error_rate_percent"] = val
        elif metric_name_with_labels.startswith("http_requests_total"):
            metrics["total_requests"] += val
            if 'status="500"' in metric_name_with_labels:
                metrics["failed_requests"] += val
        elif metric_name_with_labels.startswith("simulated_exceptions_total"):
            metrics["simulated_exceptions"] += val

    return metrics

def fetch_metrics(base_url: str) -> Optional[Dict[str, Any]]:
    """
    Fetches raw /metrics endpoint with retry mechanism.
    """
    metrics_url = f"{base_url}/metrics"
    try:
        response = session.get(metrics_url, timeout=5.0)
        response.raise_for_status()
        return parse_prometheus_metrics(response.text)
    except requests.exceptions.RequestException as e:
        logger.warning(f"Failed to scrape metrics from {metrics_url}: {e}")
        return None

def build_alert_payload(error_rate: float, total_reqs: float, error_count: float) -> Dict[str, Any]:
    """
    Constructs the exact alert payload schema mandated by the architectural specification:
    - status: 'firing'
    - severity: 'critical' or 'page'
    - service_name: 'mock-transaction-service'
    - error_signature: 'HTTP 500 rate > 5%'
    - timestamp: ISO-8601 UTC timestamp
    """
    return {
        "status": "firing",
        "severity": "critical",
        "service_name": "mock-transaction-service",
        "error_signature": f"HTTP 500 rate > {ERROR_THRESHOLD_PERCENT}% (Detected: {round(error_rate, 2)}%, Errors: {int(error_count)}/{int(total_reqs)})",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "telemetry_source": "PrometheusAlertmanagerSimulator",
        "metrics_snapshot": {
            "error_rate_percent": round(error_rate, 2),
            "total_requests": int(total_reqs),
            "failed_requests": int(error_count),
            "threshold_percent": ERROR_THRESHOLD_PERCENT
        }
    }

def dispatch_alert_with_backoff(webhook_url: str, payload: Dict[str, Any], max_attempts: int = 6) -> bool:
    """
    Transmits alert payload to n8n webhook trigger URL using exponential backoff.
    """
    delay = 1.0
    for attempt in range(1, max_attempts + 1):
        try:
            logger.info(f"Dispatching critical alert payload to n8n (attempt {attempt}/{max_attempts}): {webhook_url}")
            resp = session.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json", "User-Agent": "TelemetrySimulator/1.0"},
                timeout=10.0
            )

            if resp.status_code in (200, 201, 202):
                logger.info(f"Alert successfully acknowledged by n8n! Response [{resp.status_code}]: {resp.text}")
                return True
            else:
                logger.warning(f"Unexpected response code from n8n webhook [{resp.status_code}]: {resp.text}")

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as conn_err:
            logger.warning(f"n8n webhook unavailable ({conn_err}). Backing off for {delay:.1f}s...")
        except Exception as general_err:
            logger.error(f"Error dispatching alert: {general_err}")

        time.sleep(delay)
        delay = min(delay * 2.0, 30.0)

    logger.error(f"Failed to dispatch alert to {webhook_url} after {max_attempts} attempts.")
    return False

def background_traffic_generator():
    """
    Background worker that continuously sends transactions to the mock microservice
    so realistic metrics and log events accumulate naturally during demonstration.
    """
    target_endpoint = f"{MOCK_SERVICE_URL}/api/v1/process-transaction"
    logger.info(f"Starting background traffic generator targeting {target_endpoint}...")
    
    while True:
        try:
            # Emit a synthetic transaction
            session.post(
                target_endpoint,
                json={"amount": 99.50, "currency": "USD"},
                timeout=3.0
            )
        except Exception:
            pass  # Expected when service returns 500 or is starting
        time.sleep(1.0)

def run_telemetry_monitor(force_once: bool = False):
    """
    Continuous monitoring loop evaluating Prometheus metrics against threshold.
    """
    logger.info("Initializing Autonomous Telemetry Event Simulator...")
    logger.info(f"Target Service: {MOCK_SERVICE_URL}")
    logger.info(f"n8n Webhook:    {N8N_WEBHOOK_URL}")
    logger.info(f"Error Threshold: {ERROR_THRESHOLD_PERCENT}%")
    logger.info(f"Poll Interval:   {POLL_INTERVAL_SECONDS}s")

    if AUTO_GENERATE_TRAFFIC and not force_once:
        t = threading.Thread(target=background_traffic_generator, daemon=True)
        t.start()

    last_alert_time = 0.0

    while True:
        try:
            metrics = fetch_metrics(MOCK_SERVICE_URL)
            if metrics:
                # Calculate current error rate
                error_rate = 0.0
                if metrics["recent_error_rate_percent"] is not None:
                    error_rate = metrics["recent_error_rate_percent"]
                elif metrics["total_requests"] > 0:
                    error_rate = (metrics["failed_requests"] / metrics["total_requests"]) * 100.0

                logger.info(
                    f"Metrics Scraped: Error Rate: {error_rate:.1f}% | "
                    f"Requests: {int(metrics['total_requests'])} | "
                    f"Failures: {int(metrics['failed_requests'])}"
                )

                now = time.time()
                # Check threshold breach condition
                if (error_rate >= ERROR_THRESHOLD_PERCENT or force_once):
                    time_since_last = now - last_alert_time
                    if time_since_last >= ALERT_COOLDOWN_SECONDS or force_once:
                        logger.critical(
                            f"ALERT THRESHOLD BREACH DETECTED! Error rate ({error_rate:.1f}%) "
                            f"exceeded threshold ({ERROR_THRESHOLD_PERCENT}%)."
                        )
                        payload = build_alert_payload(
                            error_rate=error_rate,
                            total_reqs=metrics["total_requests"],
                            error_count=metrics["failed_requests"]
                        )
                        success = dispatch_alert_with_backoff(N8N_WEBHOOK_URL, payload)
                        if success:
                            last_alert_time = now

                        if force_once:
                            logger.info("Single execution requested. Exiting.")
                            break
                    else:
                        logger.info(f"Threshold exceeded but cooldown active ({int(ALERT_COOLDOWN_SECONDS - time_since_last)}s remaining).")

        except Exception as e:
            logger.error(f"Unexpected error in monitor loop: {e}")

        if force_once:
            break

        time.sleep(POLL_INTERVAL_SECONDS)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Autonomous SRE Telemetry Simulator")
    parser.add_argument("--once", action="store_true", help="Send a single simulated alert immediately and exit")
    parser.add_argument("--threshold", type=float, default=ERROR_THRESHOLD_PERCENT, help="Custom error rate threshold percent")
    parser.add_argument("--service-url", type=str, default=MOCK_SERVICE_URL, help="Mock service base URL")
    parser.add_argument("--webhook-url", type=str, default=N8N_WEBHOOK_URL, help="n8n webhook URL")
    args = parser.parse_args()

    if args.threshold:
        ERROR_THRESHOLD_PERCENT = args.threshold
    if args.service_url:
        MOCK_SERVICE_URL = args.service_url.rstrip("/")
    if args.webhook_url:
        N8N_WEBHOOK_URL = args.webhook_url

    run_telemetry_monitor(force_once=args.once)
