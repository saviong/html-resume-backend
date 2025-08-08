import os
import json
import logging

import azure.functions as func
from azure.functions import AuthLevel
from azure.data.tables import TableServiceClient
from azure.core.exceptions import ResourceNotFoundError

app = func.FunctionApp(http_auth_level=AuthLevel.ANONYMOUS)

PK_TOTAL = "counter"
RK_TOTAL = "visits"
COUNT_KEY = "count"


def _get_ip(req: func.HttpRequest) -> str:
    ip = req.headers.get(
        "x-forwarded-for") or req.headers.get("x-client-ip") or ""
    if ip and "," in ip:
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

    # Connection string
    conn = os.environ.get("COSMOS_CONNECTION_STRING")
    if not conn:
        body = json.dumps(
            {"count": "N/A", "error": "Configuration error: COSMOS_CONNECTION_STRING missing"})
        return func.HttpResponse(
            body, status_code=500, mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*",
                     "Content-Type": "application/json"}
        )

    table_name = os.environ.get("TABLE_NAME", "VisitorCounter")
    ip = _get_ip(req)

    try:
        service = TableServiceClient.from_connection_string(conn)
        table = service.get_table_client(table_name)

        # 1) IP already recorded?
        ip_seen = True
        try:
            table.get_entity(partition_key=PK_TOTAL, row_key=ip)
        except ResourceNotFoundError:
            ip_seen = False

        # 2) Load total, track existence separately (don't prefill COUNT_KEY)
        total_exists = True
        try:
            total_entity = table.get_entity(
                partition_key=PK_TOTAL, row_key=RK_TOTAL)
            total_value = int(total_entity.get(COUNT_KEY, 0))
        except ResourceNotFoundError:
            total_exists = False
            total_entity = {"PartitionKey": PK_TOTAL, "RowKey": RK_TOTAL}
            total_value = 0

        # 3) If IP already seen → DO NOT increment; return current total
        if ip_seen:
            return func.HttpResponse(
                json.dumps({"count": total_value}),
                status_code=200,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*",
                         "Content-Type": "application/json"},
            )

        # 4) First ever visit (no total & new IP) → two creates, return 1
        if not total_exists and not ip_seen:
            table.create_entity(
                # create total
                {"PartitionKey": PK_TOTAL, "RowKey": RK_TOTAL, COUNT_KEY: 1})
            # create IP
            table.create_entity({"PartitionKey": PK_TOTAL, "RowKey": ip})
            return func.HttpResponse(
                json.dumps({"count": 1}),
                status_code=200,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*",
                         "Content-Type": "application/json"},
            )

        # 5) Total exists but IP is new → create IP, update total (+1)
        table.create_entity({"PartitionKey": PK_TOTAL, "RowKey": ip})
        new_total = total_value + 1
        table.update_entity(
            {"PartitionKey": PK_TOTAL, "RowKey": RK_TOTAL, COUNT_KEY: new_total})

        return func.HttpResponse(
            json.dumps({"count": new_total}),
            status_code=200,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*",
                     "Content-Type": "application/json"},
        )

    except Exception:
        logging.exception("Function error")
        return func.HttpResponse(
            json.dumps({"count": "N/A", "error": "Server error"}),
            status_code=500,
            mimetype="application/json",
            headers={"Access-Control-Allow-Origin": "*",
                     "Content-Type": "application/json"},
        )
