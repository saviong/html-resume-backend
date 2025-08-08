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
        # test_missing_connection_string expects the phrase "Configuration error"
        body = json.dumps(
            {"count": "N/A", "error": "Configuration error: COSMOS_CONNECTION_STRING missing"})
        return func.HttpResponse(body, status_code=500, mimetype="application/json",
                                 headers={"Access-Control-Allow-Origin": "*", "Content-Type": "application/json"})

    table_name = os.environ.get("TABLE_NAME", "VisitorCounter")
    ip = _get_ip(req)

    try:
        service = TableServiceClient.from_connection_string(conn)
        table = service.get_table_client(table_name)

        # 1) Check if IP already recorded
        ip_seen = True
        try:
            table.get_entity(partition_key=PK_TOTAL, row_key=ip)
        except ResourceNotFoundError:
            ip_seen = False

        # 2) Load current total (if any)
        total = 0
        try:
            total_entity = table.get_entity(
                partition_key=PK_TOTAL, row_key=RK_TOTAL)
            total = int(total_entity.get(COUNT_KEY, 0))
        except ResourceNotFoundError:
            total_entity = {"PartitionKey": PK_TOTAL,
                            "RowKey": RK_TOTAL, COUNT_KEY: 0}

        # 3) If IP already seen → DO NOT increment; just return current total
        if ip_seen:
            return func.HttpResponse(
                json.dumps({"count": total}),
                status_code=200,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*",
                         "Content-Type": "application/json"},
            )

        # 4) New IP → create IP entity and increment total
        table.create_entity({"PartitionKey": PK_TOTAL, "RowKey": ip})

        if total == 0 and COUNT_KEY not in total_entity:
            # first ever counter create
            total_entity = {"PartitionKey": PK_TOTAL,
                            "RowKey": RK_TOTAL, COUNT_KEY: 1}
            table.create_entity(total_entity)
            new_total = 1
        else:
            new_total = total + 1
            total_entity = {"PartitionKey": PK_TOTAL,
                            "RowKey": RK_TOTAL, COUNT_KEY: new_total}
            table.update_entity(total_entity)

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
