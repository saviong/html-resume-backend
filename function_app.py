import os
import json
import logging

import azure.functions as func
from azure.functions import AuthLevel
from azure.data.tables import TableServiceClient
from azure.core.exceptions import ResourceNotFoundError

# HTTP-trigger, Python v2 model
app = func.FunctionApp(http_auth_level=AuthLevel.ANONYMOUS)


@app.function_name(name="updateCounter")
@app.route(route="updateCounter", methods=["GET", "POST", "OPTIONS"])
def update_counter(req: func.HttpRequest) -> func.HttpResponse:
    # Handle CORS preflight
    if req.method == "OPTIONS":
        return func.HttpResponse(
            "",
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Accept, Origin",
                "Access-Control-Max-Age": "3600",
            },
        )

    try:
        # Get Cosmos Table API connection string from app settings
        connection_string = os.environ.get("COSMOS_CONNECTION_STRING")
        if not connection_string:
            logging.error("COSMOS_CONNECTION_STRING is not set.")
            return func.HttpResponse(
                json.dumps(
                    {"count": "N/A", "error": "Missing connection string"}),
                status_code=500,
                mimetype="application/json",
                headers={"Access-Control-Allow-Origin": "*",
                         "Content-Type": "application/json"},
            )

        table_name = os.environ.get("TABLE_NAME", "VisitorCounter")
        partition_key = "Counter"
        row_key = "Total"

        # Connect to Table service and ensure table exists
        service = TableServiceClient.from_connection_string(
            conn_str=connection_string)
        try:
            table_client = service.get_table_client(table_name=table_name)
            # Touch the table to verify it exists
            _ = list(table_client.list_entities(results_per_page=1))
        except ResourceNotFoundError:
            service.create_table(table_name=table_name)
            table_client = service.get_table_client(table_name=table_name)

        # Fetch current count (or create if missing)
        try:
            entity = table_client.get_entity(
                partition_key=partition_key, row_key=row_key)
            current_count = int(entity.get("Count", 0))
        except ResourceNotFoundError:
            entity = {"PartitionKey": partition_key,
                      "RowKey": row_key, "Count": 0}
            table_client.create_entity(entity=entity)
            current_count = 0

        # Increment and upsert
        new_count = current_count + 1
        entity["Count"] = new_count
        table_client.upsert_entity(entity=entity)

        return func.HttpResponse(
            json.dumps({"count": new_count}),
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
