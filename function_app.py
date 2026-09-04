import os
import json
import logging
from datetime import datetime, timedelta, timezone

import azure.functions as func
from azure.functions import AuthLevel
from azure.core import MatchConditions
from azure.core.exceptions import (
    ResourceExistsError,
    ResourceModifiedError,
    ResourceNotFoundError,
)
from azure.data.tables import TableServiceClient, UpdateMode

app = func.FunctionApp(http_auth_level=AuthLevel.ANONYMOUS)

# Table layout
PK_TOTAL = "counter"
RK_TOTAL = "visits"
PK_VISITOR = "visitor"
COUNT_KEY = "count"
VISIT_TIME_KEY = "lastVisit"

REVISIT_WINDOW = timedelta(hours=1)
MAX_INCREMENT_ATTEMPTS = 5

# Cached across warm invocations; creating a client per request rebuilds the
# TLS connection pool every time.
_table_client = None


def _get_table_client(conn_str: str):
    global _table_client
    if _table_client is None:
        table_name = os.environ.get("TABLE_NAME", "VisitorCounter")
        service = TableServiceClient.from_connection_string(conn_str)
        _table_client = service.get_table_client(table_name)
    return _table_client


def _cors_headers(req: func.HttpRequest) -> dict:
    """
    CORS is handled here rather than by the Function App's platform CORS setting.
    Leave the platform allowed-origins list empty, otherwise the platform appends a
    second Access-Control-Allow-Origin header and browsers reject the response.
    """
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Vary": "Origin",
    }
    allowed = [o.strip() for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
    origin = req.headers.get("Origin", "")
    if allowed == ["*"]:
        headers["Access-Control-Allow-Origin"] = "*"
    elif origin in allowed:
        headers["Access-Control-Allow-Origin"] = origin
    return headers


def _get_ip(req: func.HttpRequest) -> str:
    """Client IP from the proxy headers, first hop only."""
    ip = req.headers.get("x-forwarded-for") or req.headers.get("x-client-ip") or ""
    if "," in ip:
        ip = ip.split(",")[0]
    ip = ip.strip()
    # x-forwarded-for on Azure Functions carries "ip:port".
    if ip.count(":") == 1:
        ip = ip.split(":")[0]
    return ip or "unknown"


def _parse_last_visit(entity) -> datetime:
    """
    Tolerate entities written before this field existed, or stored as an Edm.DateTime
    rather than an ISO string. Returns a value in the distant past when unusable, so
    the visit is treated as new instead of raising.
    """
    raw = entity.get(VISIT_TIME_KEY)
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, str):
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            logging.warning("Unparseable %s value on visitor entity", VISIT_TIME_KEY)
    return datetime.min.replace(tzinfo=timezone.utc)


def _should_count(table_client, ip: str, now: datetime) -> bool:
    """True when this IP has not been counted inside the revisit window."""
    try:
        table_client.create_entity(
            {"PartitionKey": PK_VISITOR, "RowKey": ip, VISIT_TIME_KEY: now.isoformat()}
        )
        return True
    except ResourceExistsError:
        pass

    visitor = table_client.get_entity(partition_key=PK_VISITOR, row_key=ip)
    if now - _parse_last_visit(visitor) < REVISIT_WINDOW:
        return False

    visitor[VISIT_TIME_KEY] = now.isoformat()
    try:
        table_client.update_entity(
            visitor,
            mode=UpdateMode.REPLACE,
            etag=visitor.metadata["etag"],
            match_condition=MatchConditions.IfNotModified,
        )
    except ResourceModifiedError:
        # Another concurrent request for this IP already refreshed the timestamp.
        return False
    return True


def _read_total(table_client) -> int:
    try:
        return int(table_client.get_entity(PK_TOTAL, RK_TOTAL).get(COUNT_KEY, 0))
    except ResourceNotFoundError:
        return 0


def _increment_total(table_client) -> int:
    """
    Increment under optimistic concurrency. The previous version read the total and
    wrote back an unconditional REPLACE, so two overlapping requests both wrote the
    same value and one increment was silently lost.
    """
    for _ in range(MAX_INCREMENT_ATTEMPTS):
        try:
            total = table_client.get_entity(PK_TOTAL, RK_TOTAL)
        except ResourceNotFoundError:
            try:
                table_client.create_entity(
                    {"PartitionKey": PK_TOTAL, "RowKey": RK_TOTAL, COUNT_KEY: 1}
                )
                return 1
            except ResourceExistsError:
                continue  # created by a concurrent request; re-read and retry

        new_value = int(total.get(COUNT_KEY, 0)) + 1
        total[COUNT_KEY] = new_value
        try:
            table_client.update_entity(
                total,
                mode=UpdateMode.REPLACE,
                etag=total.metadata["etag"],
                match_condition=MatchConditions.IfNotModified,
            )
            return new_value
        except ResourceModifiedError:
            continue  # lost the race; re-read and retry

    logging.warning("Gave up incrementing the total after %d attempts", MAX_INCREMENT_ATTEMPTS)
    return _read_total(table_client)


@app.function_name("updateCounter")
@app.route(route="updateCounter", methods=["GET", "POST", "OPTIONS"])
def update_counter(req: func.HttpRequest) -> func.HttpResponse:
    """Total visit count, incrementing at most once per IP per hour."""
    headers = _cors_headers(req)

    if req.method == "OPTIONS":
        preflight = dict(headers)
        preflight.update({
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Max-Age": "86400",
        })
        return func.HttpResponse("", status_code=204, headers=preflight)

    conn_str = os.environ.get("COSMOS_CONNECTION_STRING")
    if not conn_str:
        logging.error("COSMOS_CONNECTION_STRING is not set")
        return func.HttpResponse(
            json.dumps({"count": "N/A", "error": "Configuration error"}),
            status_code=500,
            headers=headers,
        )

    try:
        table_client = _get_table_client(conn_str)
        now = datetime.now(timezone.utc)
        if _should_count(table_client, _get_ip(req), now):
            count = _increment_total(table_client)
        else:
            count = _read_total(table_client)
        return func.HttpResponse(json.dumps({"count": count}), status_code=200, headers=headers)
    except Exception:
        logging.exception("updateCounter failed")
        return func.HttpResponse(
            json.dumps({"count": "N/A", "error": "Server error"}),
            status_code=500,
            headers=headers,
        )
