import os
import json
import logging

import azure.functions as func
from azure.functions import AuthLevel
from azure.data.tables import TableServiceClient
from azure.core.exceptions import ResourceNotFoundError

app = func.FunctionApp(http_auth_level=AuthLevel.ANONYMOUS)

TABLE_ENV_NAME = "TABLE_NAME"
DEFAULT_TABLE_NAME = "VisitorCounter"

PARTITION_TOTAL = "Counter"
ROW_TOTAL = "Total"

PARTITION_IP = "IP"  # each IP stored as PK="IP", RK="<ip-address>"


def _get_ip(req: func.HttpRequest) -> str:
    # Try CDN / proxy header first
    ip = req.headers.get(
        "x-forwarded-for", "") or req.headers.get("x-client-ip", "")
    # In “x-forwarded-for: client, proxy1, proxy2” we take the first
    if "," in ip:
        ip = ip.split(",")[0].strip()
    return ip or "unknown"


@app.function_name(name="updateCounter")
@app.route(route="updateCounter", methods=["GET", "POST", "OPTIONS"])
def update_counter(req: func.HttpRequest) -> func.HttpResponse:
    # CORS preflight
    if req.method == "OPTIONS":
        return func.HttpResponse(
            "",
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Accept, Origin, x-forwarded-for",
                "Access-Control-Max-Age": "3600",
            },
        )

    try:
        conn = os.environ.get("COSMOS_CONNECTION_STRING")
        if not conn:
            # Tests expect the phrase "Configuration error"
            body = json.dumps(
                {"count": "N/A", "error": "Configuration error: COSMOS_CONNECTION_STRING missing"})
            return func.HttpResponse(
                body, status_code=500, mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*",
                         "Content-Type": "application/json"}
            )

        table_name = os.environ.get(TABLE_ENV_NAME, DEFAULT_TABLE_NAME)
        ip = _get_ip(req)

        service = TableServiceClient.from_connection_string(conn)
        # Ensure table exists
        try:
            table = service.get_table_client(table_name)
            # touch to ensure existence; will raise if missing
            _ = list(table.list_entities(results_per_page=1))
        except ResourceNotFoundError:
            service.create_table(table_name=table_name)
            table = service.get_table_client(table_name=table_name)

        # 1) Ensure TOTAL entity exists
        created_total = False
        try:
            total = table.get_entity(
                partition_key=PARTITION_TOTAL, row_key=ROW_TOTAL)
            total_count = int(total.get("Count", 0))
        except ResourceNotFoundError:
            total = {"PartitionKey": PARTITION_TOTAL,
                     "RowKey": ROW_TOTAL, "Count": 0}
            table.create_entity(entity=total)
            total_count = 0
            created_total = True

        # 2) Ensure IP entity exists
        created_ip = False
        try:
            _ = table.get_entity(partition_key=PARTITION_IP, row_key=ip)
        except ResourceNotFoundError:
            ip_entity = {"PartitionKey": PARTITION_IP, "RowKey": ip}
            table.create_entity(entity=ip_entity)
            created_ip = True

        # 3) Increment TOTAL and upsert
        new_total = total_count + 1
        total["Count"] = new_total
        table.upsert_entity(entity=total)

        # For debugging if you need it:
        logging.info(
            f"Incremented total from {total_count} to {new_total} (created_total={created_total}, created_ip={created_ip}, ip={ip})")

        return func.HttpResponse(
            json.dumps({"count": new_total}),
            status_code=200,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*",
                     "Content-Type": "application/json"},
        )

    except Exception as e:
        logging.exception("Function error")
        return func.HttpResponse(
            json.dumps({"count": "N/A", "error": "Server error"}),
            status_code=500,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*",
                     "Content-Type": "application/json"},
        )
