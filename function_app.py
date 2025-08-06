import azure.functions as func
from azure.functions import AuthLevel, HttpRequest, HttpResponse
from azure.data.tables import TableServiceClient
import os
import logging

app = func.FunctionApp(http_auth_level=AuthLevel.ANONYMOUS)


@app.function_name(name="updateCounter")
# Allow both GET and POST
@app.route(route="updateCounter", methods=["GET", "POST"])
def main(req: HttpRequest) -> HttpResponse:
    try:
        # Add CORS headers
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
            "Content-Type": "application/json"
        }

        connection_string = os.environ.get("COSMOS_CONNECTION_STRING")
        if not connection_string:
            logging.error(
                "COSMOS_CONNECTION_STRING environment variable not found")
            return HttpResponse('{"count": "N/A", "error": "Configuration error"}',
                                status_code=500, headers=headers)

        table_name = "VisitCounter"
        partition_key = "counter"
        row_key_counter = "visits"

        service = TableServiceClient.from_connection_string(
            conn_str=connection_string)
        table = service.get_table_client(table_name=table_name)

        # Get IP address with multiple fallback options
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
            # Fallback to a default IP for testing
            ip_address = "unknown"
            logging.warning("Could not determine IP address, using 'unknown'")

        logging.info(f"Processing request from IP: {ip_address}")

        # Check if this IP has already been counted
        ip_exists = False
        try:
            table.get_entity(partition_key=partition_key, row_key=ip_address)
            ip_exists = True
            logging.info(f"IP {ip_address} already counted")
        except Exception as e:
            logging.info(
                f"IP {ip_address} not found, will count as new visitor: {str(e)}")

        # Get or create the main counter
        try:
            counter_entity = table.get_entity(
                partition_key=partition_key, row_key=row_key_counter)
            current_count = counter_entity.get("count", 0)
        except Exception as e:
            logging.info(
                f"Counter entity not found, creating new one: {str(e)}")
            current_count = 0
            counter_entity = {
                "PartitionKey": partition_key,
                "RowKey": row_key_counter,
                "count": 0
            }
            table.create_entity(counter_entity)

        # If IP hasn't been counted before, increment counter and record IP
        if not ip_exists:
            try:
                # Record the new IP
                table.create_entity({
                    "PartitionKey": partition_key,
                    "RowKey": ip_address,
                    "timestamp": func.datetime.datetime.utcnow().isoformat()
                })

                # Increment the counter
                current_count += 1
                counter_entity["count"] = current_count
                table.update_entity(counter_entity)

                logging.info(
                    f"New visitor counted. Total count: {current_count}")
            except Exception as e:
                logging.error(f"Error updating counter: {str(e)}")
                return HttpResponse(f'{{"count": {current_count}, "error": "Update failed"}}',
                                    headers=headers, status_code=500)

        return HttpResponse(f'{{"count": {current_count}}}', headers=headers)

    except Exception as e:
        logging.error(f"Function error: {str(e)}")
        return HttpResponse(f'{{"count": "N/A", "error": "{str(e)}"}}',
                            status_code=500,
                            headers={
            "Access-Control-Allow-Origin": "*",
            "Content-Type": "application/json"
        })
