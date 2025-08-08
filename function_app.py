import azure.functions as func
from azure.functions import AuthLevel
from azure.data.tables import TableServiceClient
from azure.core.exceptions import ResourceNotFoundError
import os
import logging
import json

# Initialize the Function App
app = func.FunctionApp(http_auth_level=AuthLevel.ANONYMOUS)


@app.function_name(name="updateCounter")
@app.route(route="updateCounter", methods=["GET", "POST", "OPTIONS"])
def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info('Python HTTP trigger function processed a request.')

    # Handle CORS preflight requests
    if req.method == "OPTIONS":
        return func.HttpResponse(
            "",
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Accept, Origin",
                "Access-Control-Max-Age": "3600"
            }
        )

    try:
        # Check for connection string
        connection_string = os.environ.get("COSMOS_CONNECTION_STRING")
        if not connection_string:
            logging.error(
                "COSMOS_CONNECTION_STRING environment variable not found")
            return func.HttpResponse(
                json.dumps({"count": "N/A", "error": "Configuration error"}),
                status_code=500,
                mimetype="application/json",
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Content-Type": "application/json"
                }
            )

        table_name = "VisitCounter"
        partition_key = "counter"
        row_key_counter = "visits"

        # Initialize table service
        service = TableServiceClient.from_connection_string(
            conn_str=connection_string)
        table = service.get_table_client(table_name=table_name)

        # Get IP address
        ip_address = req.headers.get(
            "x-forwarded-for", "").split(",")[0].strip()
        if not ip_address:
            ip_address = req.headers.get("x-real-ip", "")
        if not ip_address:
            ip_address = req.headers.get("x-client-ip", "")
        if not ip_address:
            ip_address = "unknown"

        logging.info(f"Processing request from IP: {ip_address}")

        # Check if this IP has already been counted
        ip_exists = False
        try:
            table.get_entity(partition_key=partition_key, row_key=ip_address)
            ip_exists = True
            logging.info(f"IP {ip_address} already counted")
        except ResourceNotFoundError:
            logging.info(
                f"IP {ip_address} not found, will count as new visitor")
        except Exception as e:
            logging.error(f"Error checking IP: {str(e)}")

        # Get the main counter
        current_count = 0
        counter_entity = None
        try:
            counter_entity = table.get_entity(
                partition_key=partition_key, row_key=row_key_counter)
            current_count = counter_entity.get("count", 0)
            logging.info(
                f"Current count from existing counter: {current_count}")
        except ResourceNotFoundError:
            logging.info("Counter entity not found, will create new one")
        except Exception as e:
            logging.error(f"Error getting counter: {str(e)}")

        # If IP hasn't been counted before, increment counter and record IP
        if not ip_exists:
            try:
                # Record the new IP
                table.create_entity({
                    "PartitionKey": partition_key,
                    "RowKey": ip_address
                })
                logging.info(f"Created entity for new IP: {ip_address}")

                # Increment the counter
                current_count += 1

                if counter_entity is None:
                    # Create new counter entity (first visit ever)
                    counter_entity = {
                        "PartitionKey": partition_key,
                        "RowKey": row_key_counter,
                        "count": current_count
                    }
                    table.create_entity(counter_entity)
                    logging.info(
                        f"Created new counter entity with count: {current_count}")
                else:
                    # Update existing counter entity
                    counter_entity["count"] = current_count
                    table.update_entity(counter_entity)
                    logging.info(
                        f"Updated counter entity to count: {current_count}")

            except Exception as e:
                logging.error(f"Error updating counter: {str(e)}")
                return func.HttpResponse(
                    json.dumps({"count": "N/A", "error": "Database error"}),
                    status_code=500,
                    mimetype="application/json",
                    headers={
                        "Access-Control-Allow-Origin": "*",
                        "Content-Type": "application/json"
                    }
                )

        # Return success response
        return func.HttpResponse(
            json.dumps({"count": current_count}),
            status_code=200,
            mimetype="application/json",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Content-Type": "application/json"
            }
        )

    except Exception as e:
        logging.error(f"Function error: {str(e)}")
        return func.HttpResponse(
            json.dumps({"count": "N/A", "error": "Server error"}),
            status_code=500,
            mimetype="application/json",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Content-Type": "application/json"
            }
        )
