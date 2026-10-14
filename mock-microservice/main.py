"""
Mock Unstable Microservice - Autonomous AI SRE Target Application
=================================================================
This microservice simulates a production payment and ledger transaction processing
service designed to intentionally exhibit stochastic failure modes, structured JSON logging,
and Prometheus telemetry metrics.
"""

import os
import sys
import time
import uuid
import random
import logging
import traceback
from datetime import datetime, timezone
from collections import deque
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, Request, Response, status, Query, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
import prometheus_client
from prometheus_client import Counter, Gauge, generate_latest, CONTENT_TYPE_LATEST
from pythonjsonlogger import jsonlogger

# ---------------------------------------------------------------------------
# Global In-Memory Log Buffer & Structured Logging Configuration
# ---------------------------------------------------------------------------
LOG_BUFFER_SIZE = 200
log_record_buffer: deque = deque(maxlen=LOG_BUFFER_SIZE)

class InMemoryLogHandler(logging.Handler):
    """
    Custom in-memory log handler retaining the last N structured log entries
    for forensic extraction via the /logs endpoint by the SRE Incident Commander.
    """
    def emit(self, record: logging.LogRecord) -> None:
        try:
            log_entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "correlation_id": getattr(record, "correlation_id", "none"),
                "function": getattr(record, "function_name", record.funcName),
                "module": record.module,
                "message": record.getMessage(),
            }
            if record.exc_info:
                log_entry["exception_type"] = record.exc_info[0].__name__ if record.exc_info[0] else "Exception"
                log_entry["exception_message"] = str(record.exc_info[1]) if record.exc_info[1] else ""
                log_entry["stack_trace"] = traceback.format_exception(*record.exc_info)
            elif hasattr(record, "stack_trace"):
                log_entry["stack_trace"] = record.stack_trace

            log_record_buffer.append(log_entry)
        except Exception:
            self.handleError(record)


# Configure Python JSON Logger for stdout
logger = logging.getLogger("mock_microservice")
logger.setLevel(logging.DEBUG)

# Avoid duplicate handlers on reload
if not logger.handlers:
    # Stdout Stream Handler with JsonFormatter
    stdout_handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        fmt="%(timestamp)s %(level)s %(correlation_id)s %(function_name)s %(message)s",
        rename_fields={"levelname": "level"}
    )
    stdout_handler.setFormatter(formatter)
    logger.addHandler(stdout_handler)

    # In-memory buffer handler
    memory_handler = InMemoryLogHandler()
    logger.addHandler(memory_handler)

# ---------------------------------------------------------------------------
# Prometheus Metric Primitives
# ---------------------------------------------------------------------------
HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests processed by endpoint and status code",
    ["method", "endpoint", "status"]
)

SIMULATED_EXCEPTIONS_TOTAL = Counter(
    "simulated_exceptions_total",
    "Total simulated catastrophic exceptions thrown",
    ["exception_type", "error_code"]
)

RECENT_ERROR_RATE_GAUGE = Gauge(
    "recent_error_rate_percent",
    "Current error rate percentage across recent transaction window"
)

SERVICE_HEALTH_GAUGE = Gauge(
    "service_health_status",
    "Service operational state (1 = Healthy, 0 = Degraded/Unstable)"
)
SERVICE_HEALTH_GAUGE.set(1)

TRANSACTION_PROCESSING_TIME = Gauge(
    "transaction_processing_duration_seconds",
    "Duration of transaction execution in seconds"
)

# Rolling window for calculating real-time error percentage
WINDOW_SIZE = 50
recent_outcomes: deque = deque(maxlen=WINDOW_SIZE)

def update_error_gauge(is_error: bool) -> None:
    recent_outcomes.append(1 if is_error else 0)
    if recent_outcomes:
        rate = (sum(recent_outcomes) / len(recent_outcomes)) * 100.0
        RECENT_ERROR_RATE_GAUGE.set(round(rate, 2))
        SERVICE_HEALTH_GAUGE.set(0 if rate >= 5.0 else 1)

# ---------------------------------------------------------------------------
# Custom Synthetic Failure Exceptions
# ---------------------------------------------------------------------------
class SimulatedNullPointerException(Exception):
    """Simulated Java/Python unhandled null reference crash."""
    pass

class SimulatedDatabaseConnectionTimeout(Exception):
    """Simulated persistent database pool exhaustion."""
    pass

class SimulatedIndexOutOfBoundsError(Exception):
    """Simulated boundary condition violation in batch partitioner."""
    pass

# ---------------------------------------------------------------------------
# FastAPI Application & Chaos Config
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Mock Enterprise Transaction Service",
    description="Intentionally unstable microservice for Autonomous AI SRE Incident Commander validation",
    version="1.2.4-hotfix-pending"
)

# Global chaos state (can be toggled for instant judge demonstration)
class ChaosConfig:
    failure_probability: float = float(os.getenv("DEFAULT_FAILURE_PROBABILITY", "0.20")) # 20% default to ensure rapid threshold breach
    is_active: bool = True
    active_canary_version: str = "v1.2.4-buggy-commit"

chaos_state = ChaosConfig()

# Pydantic Schemas
class TransactionPayload(BaseModel):
    account_id: str = Field(default_factory=lambda: f"act_{uuid.uuid4().hex[:8]}")
    amount: float = Field(default=149.99, gt=0)
    currency: str = Field(default="USD")
    idempotency_key: Optional[str] = None

class ChaosUpdatePayload(BaseModel):
    failure_probability: float = Field(..., ge=0.0, le=1.0)
    is_active: bool

# ---------------------------------------------------------------------------
# Middleware: Correlation ID & Request Tracing
# ---------------------------------------------------------------------------
@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID") or f"corr-{uuid.uuid4()}"
    request.state.correlation_id = correlation_id
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response

# ---------------------------------------------------------------------------
# Core Endpoints
# ---------------------------------------------------------------------------
@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    """
    Standard health check endpoint returning 200 OK.
    """
    return {
        "status": "UP",
        "service": "mock-transaction-service",
        "version": chaos_state.active_canary_version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "recent_error_rate_percent": RECENT_ERROR_RATE_GAUGE._value.get(),
        "healthy": SERVICE_HEALTH_GAUGE._value.get() == 1
    }

@app.get("/metrics")
async def metrics_endpoint():
    """
    Prometheus metrics scraping endpoint used by the Telemetry Simulator.
    """
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/logs")
async def get_forensic_logs(limit: int = Query(default=50, ge=1, le=200)):
    """
    Returns the forensic rolling buffer of recent structured JSON container logs,
    allowing the SRE Incident Commander agent to ingest the preceding 15 minutes of evidence.
    """
    logs_slice = list(log_record_buffer)[-limit:]
    return {
        "service_name": "mock-transaction-service",
        "total_buffered": len(log_record_buffer),
        "returned": len(logs_slice),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "logs": logs_slice
    }

@app.api_route("/api/v1/process-transaction", methods=["GET", "POST"])
async def process_transaction(
    request: Request,
    payload: Optional[TransactionPayload] = None,
    force_error: Optional[str] = Query(default=None, description="Force a specific error: npe, db, index, or random")
):
    """
    Primary transactional endpoint designed to exhibit stochastic failure modes.
    Fails based on failure_probability or force_error query parameter.
    """
    correlation_id = getattr(request.state, "correlation_id", f"corr-{uuid.uuid4()}")
    start_time = time.time()
    
    # Determine if failure should be triggered
    should_fail = False
    if force_error:
        should_fail = True
    elif chaos_state.is_active and random.random() < chaos_state.failure_probability:
        should_fail = True

    if should_fail:
        # Determine error variant
        error_types = ["npe", "db", "index"]
        selected_error = force_error if force_error in error_types else random.choice(error_types)

        try:
            if selected_error == "npe":
                # Simulated NullPointerException in ledger validator
                raise SimulatedNullPointerException(
                    "NullPointerException: Object reference not set to an instance of an object "
                    "at LedgerAccountManager.validate_balance(account_id=None). Line 142 in ledger_manager.py"
                )
            elif selected_error == "db":
                # Simulated DatabaseConnectionTimeout in connection pool
                raise SimulatedDatabaseConnectionTimeout(
                    "DatabaseConnectionTimeout: Connection pool exhausted after 30000ms attempting "
                    "to acquire connection to cluster 'pg-primary-replica.internal:5432'. Max pool size 20 reached."
                )
            else:
                # Simulated IndexOutOfBoundsError in batch partitioner
                raise SimulatedIndexOutOfBoundsError(
                    "IndexOutOfBoundsError: List index 25 out of range in TransactionBatchProcessor.partition_chunks(batch_size=24). "
                    "Array index overflow during parallel commit synchronization."
                )
        except Exception as exc:
            duration = time.time() - start_time
            TRANSACTION_PROCESSING_TIME.set(duration)
            exc_name = exc.__class__.__name__

            # Increment metrics
            HTTP_REQUESTS_TOTAL.labels(method=request.method, endpoint="/api/v1/process-transaction", status="500").inc()
            SIMULATED_EXCEPTIONS_TOTAL.labels(exception_type=exc_name, error_code="ERR_SYS_FATAL").inc()
            update_error_gauge(is_error=True)

            # Emit structured JSON log with multi-line traceback
            logger.error(
                f"Catastrophic transaction failure: {str(exc)}",
                exc_info=True,
                extra={
                    "correlation_id": correlation_id,
                    "function_name": "process_transaction",
                    "execution_path": "/api/v1/process-transaction",
                    "exception_type": exc_name,
                    "duration_seconds": round(duration, 4),
                    "service_version": chaos_state.active_canary_version
                }
            )

            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "error": True,
                    "status_code": 500,
                    "error_type": exc_name,
                    "message": str(exc),
                    "correlation_id": correlation_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "suggested_action": "Contact On-Call SRE or await autonomous remediation"
                }
            )

    # Success execution pathway
    duration = time.time() - start_time
    TRANSACTION_PROCESSING_TIME.set(duration)
    HTTP_REQUESTS_TOTAL.labels(method=request.method, endpoint="/api/v1/process-transaction", status="200").inc()
    update_error_gauge(is_error=False)

    tx_id = f"tx_{uuid.uuid4().hex[:12]}"
    logger.info(
        f"Transaction {tx_id} completed successfully",
        extra={
            "correlation_id": correlation_id,
            "function_name": "process_transaction",
            "transaction_id": tx_id,
            "duration_seconds": round(duration, 4)
        }
    )

    return {
        "status": "completed",
        "transaction_id": tx_id,
        "correlation_id": correlation_id,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "amount": payload.amount if payload else 149.99,
        "currency": payload.currency if payload else "USD"
    }

# ---------------------------------------------------------------------------
# Control & Chaos Management (For Hackathon Demonstrator)
# ---------------------------------------------------------------------------
@app.post("/api/v1/chaos/configure")
async def configure_chaos(config: ChaosUpdatePayload):
    """
    Allows live tuning of chaos failure probability for live judge presentations.
    """
    chaos_state.failure_probability = config.failure_probability
    chaos_state.is_active = config.is_active
    logger.warning(
        f"Chaos configuration updated: probability={config.failure_probability}, active={config.is_active}",
        extra={
            "correlation_id": f"admin-{uuid.uuid4().hex[:6]}",
            "function_name": "configure_chaos"
        }
    )
    return {
        "message": "Chaos configuration updated",
        "failure_probability": chaos_state.failure_probability,
        "is_active": chaos_state.is_active
    }

@app.post("/api/v1/rollback")
async def trigger_canary_rollback(request: Request):
    """
    Endpoint targeted by the SRE Incident Commander when action_decision == TRIGGER_ROLLBACK.
    Reverts canary deployment to stable version and restores baseline error rates.
    """
    correlation_id = getattr(request.state, "correlation_id", f"rollback-{uuid.uuid4().hex[:6]}")
    previous_version = chaos_state.active_canary_version
    chaos_state.active_canary_version = "v1.2.3-stable"
    chaos_state.failure_probability = 0.0
    recent_outcomes.clear()
    RECENT_ERROR_RATE_GAUGE.set(0.0)
    SERVICE_HEALTH_GAUGE.set(1)

    logger.info(
        f"Autonomous Canary Rollback executed: reverted {previous_version} -> v1.2.3-stable",
        extra={
            "correlation_id": correlation_id,
            "function_name": "trigger_canary_rollback",
            "previous_version": previous_version,
            "active_version": chaos_state.active_canary_version
        }
    )

    return {
        "status": "ROLLBACK_SUCCESSFUL",
        "active_version": chaos_state.active_canary_version,
        "previous_version": previous_version,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": "Target service state restored to stable release baseline"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
