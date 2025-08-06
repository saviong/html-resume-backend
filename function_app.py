import azure.functions as func
from azure.functions import AuthLevel, HttpRequest, HttpResponse
from azure.data.tables import TableServiceClient
import os
import logging
import json
from datetime import datetime  # Import datetime properly

app = func.FunctionApp(http_auth_level=AuthLevel.ANONYMOUS)


@app.function_name(name="updateCounter")
@app.route(route="updateCounter", methods=["GET", "POST", "OPTIONS"])
def main(req: HttpRequest) -> HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    # Handle CORS preflight requests
    if req.method == "OPTIONS":
        return HttpResponse(
            "",
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Accept, Origin",
                "Access-Control-Max-Age": "3600"
            }
        )

    # CORS headers for all responses
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Accept, Origin",
        "Content-Type": "application/json"
    }

    try:
        # Check for connection string
        connection_string = os.environ.get("COSMOS_CONNECTION_STRING")
        if not connection_string:
            logging.error(
                "COSMOS_CONNECTION_STRING environment variable not found")
            return HttpResponse(
                json.dumps({"count": "N/A", "error": "Configuration error"}),
                status_code=500,
                headers=headers
            )

        table_name = "VisitCounter"
        partition_key = "counter"
        row_key_counter = "visits"

        # Initialize table service
        service = TableServiceClient.from_connection_string(
            conn_str=connection_string)
        table = service.get_table_client(table_name=table_name)

        # Get IP address with fallback options
        ip_address = None

        # Try different header combinations
        forwarded_for = req.headers.get("x-forwarded-for", "")
        if forwarded_for:
            ip_address = forwarded_for.split(",")[0].strip()

        if not ip_address:
            ip_address = req.headers.get("x-real-ip", "")

        if not ip_address:
            ip_address = req.headers.get("x-client-ip", "")

        if not ip_address:
            # Return 400 for missing IP as expected by your tests
            return HttpResponse(
                json.dumps({"error": "IP address not found"}),
                status_code=400,
                headers=headers
            )

        logging.info(f"Processing request from IP: {ip_address}")

        # Check if this IP has already been counted
        ip_exists = False
        try:
            table.get_entity(partition_key=partition_key, row_key=ip_address)
            ip_exists = True
        except Exception:
            pass  # IP not found, it's a new visitor

        # Get or create the main counter
        current_count = 0
        try:
            counter_entity = table.get_entity(
                partition_key=partition_key, row_key=row_key_counter)
            current_count = counter_entity.get("count", 0)
        except Exception:
            # Counter doesn't exist, create it
            counter_entity = {
                "PartitionKey": partition_key,
                "RowKey": row_key_counter,
                "count": 0
            }
            table.create_entity(counter_entity)

        # If IP hasn't been counted before, increment counter and record IP
        if not ip_exists:
            try:
                # Record the new IP with proper datetime import
                table.create_entity({
                    "PartitionKey": partition_key,
                    "RowKey": ip_address,
                    "timestamp": datetime.utcnow().isoformat()  # Fixed: use datetime.utcnow()
                })

                # Increment the counter
                current_count += 1
                counter_entity["count"] = current_count
                table.update_entity(counter_entity)

                logging.info(
                    f"New visitor counted. Total count: {current_count}")
            except Exception as e:
                logging.error(f"Error updating counter: {str(e)}")
                return HttpResponse(
                    json.dumps({"count": "N/A", "error": "Database error"}),
                    status_code=500,
                    headers=headers
                )

        return HttpResponse(
            json.dumps({"count": current_count}),
            status_code=200,
            headers=headers
        )

    except Exception as e:
        logging.error(f"Function error: {str(e)}")
        return HttpResponse(
            json.dumps({"count": "N/A", "error": "Server error"}),
            status_code=500,
            headers=headers
        )
