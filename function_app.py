import os
import json
import logging
from datetime import datetime, timedelta, timezone

import azure.functions as func
from azure.functions import AuthLevel
from azure.data.tables import TableServiceClient, UpdateMode
from azure.core.exceptions import ResourceNotFoundError

app = func.FunctionApp(http_auth_level=AuthLevel.ANONYMOUS)

# Define constants for table storage
PK_TOTAL = "counter"
RK_TOTAL = "visits"
PK_VISITOR = "visitor"
COUNT_KEY = "count"
VISIT_TIME_KEY = "lastVisit"

def _get_ip(req: func.HttpRequest) -> str:
    """Retrieves the client's IP address from the request headers."""
    ip = req.headers.get("x-forwarded-for") or req.headers.get("x-client-ip") or ""
    if ip and "," in ip:
        ip = ip.split(",")[0].strip()
    return ip or "unknown"


@app.function_name("updateCounter")
@app.route(route="updateCounter", methods=["GET", "POST", "OPTIONS"])
def update_counter(req: func.HttpRequest) -> func.HttpResponse:
    """
    Increments a visitor counter, but only counts a unique IP address
    once per hour.
    """
    # --- THIS IS THE KEY CHANGE: Define headers to disable caching ---
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Content-Type": "application/json",
        "Cache-Control": "no-store, no-cache, must-revalidate",
    }

    if req.method == "OPTIONS":
        # Add CORS headers for preflight request
        options_headers = headers.copy()
        options_headers.update({
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Max-Age": "86400"
        })
        return func.HttpResponse("", status_code=200, headers=options_headers)
    
    conn_str = os.environ.get("COSMOS_CONNECTION_STRING")
    if not conn_str:
        body = json.dumps({"count": "N/A", "error": "Configuration error"})
        return func.HttpResponse(body, status_code=500, headers=headers)

    table_name = os.environ.get("TABLE_NAME", "VisitorCounter")
    ip = _get_ip(req)
    now = datetime.now(timezone.utc)

    try:
        table_service = TableServiceClient.from_connection_string(conn_str)
        table_client = table_service.get_table_client(table_name)

        try:
            total_entity = table_client.get_entity(partition_key=PK_TOTAL, row_key=RK_TOTAL)
            total_value = int(total_entity.get(COUNT_KEY, 0))
        except ResourceNotFoundError:
            total_entity = None
            total_value = 0

        try:
            visitor_entity = table_client.get_entity(partition_key=PK_VISITOR, row_key=ip)
            last_visit_str = visitor_entity.get(VISIT_TIME_KEY)
            
            if last_visit_str:
                last_visit = datetime.fromisoformat(last_visit_str)
                if now - last_visit < timedelta(hours=1):
                    # Use the standard headers on all return paths
                    return func.HttpResponse(json.dumps({"count": total_value}), status_code=200, headers=headers)
            
        except ResourceNotFoundError:
            visitor_entity = None
        
        new_total = total_value + 1

        if total_entity:
            total_entity[COUNT_KEY] = new_total
            table_client.update_entity(total_entity, mode=UpdateMode.REPLACE)
        else:
            table_client.create_entity({"PartitionKey": PK_TOTAL, "RowKey": RK_TOTAL, COUNT_KEY: 1})

        visitor_payload = {
            "PartitionKey": PK_VISITOR,
            "RowKey": ip,
            VISIT_TIME_KEY: now.isoformat()
        }
        if visitor_entity:
            table_client.update_entity(visitor_payload, mode=UpdateMode.REPLACE)
        else:
            table_client.create_entity(visitor_payload)

        # Use the standard headers on all return paths
        return func.HttpResponse(json.dumps({"count": new_total}), status_code=200, headers=headers)

    except Exception as e:
        logging.exception(f"Function error: {e}")
        error_body = json.dumps({"count": "N/A", "error": "Server error"})
        # Use the standard headers on all return paths
        return func.HttpResponse(error_body, status_code=500, headers=headers)