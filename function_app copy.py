import azure.functions as func
from azure.functions import AuthLevel, HttpRequest, HttpResponse
from azure.data.tables import TableServiceClient
import os

app = func.FunctionApp(http_auth_level=AuthLevel.ANONYMOUS)


@app.function_name(name="updateCounter")
@app.route(route="updateCounter")  # route: /api/updateCounter
def main(req: HttpRequest) -> HttpResponse:
    try:
        connection_string = os.environ["COSMOS_CONNECTION_STRING"]
        table_name = "VisitCounter"

        service = TableServiceClient.from_connection_string(
            conn_str=connection_string)
        table = service.get_table_client(table_name=table_name)

        partition_key = "counter"
        row_key_counter = "visits"

        # 1. Get IP from x-forwarded-for header
        ip_address = req.headers.get(
            "x-forwarded-for", "").split(",")[0].strip()
        if not ip_address:
            return HttpResponse("IP address not found", status_code=400)

        # 2. Check if IP already exists
        try:
            table.get_entity(partition_key=partition_key, row_key=ip_address)
            # IP already counted, return current count
            entity = table.get_entity(
                partition_key=partition_key, row_key=row_key_counter)
            return HttpResponse(f'{{"count": {entity["count"]}}}', mimetype="application/json")
        except:
            # IP not found, it's a new visitor
            # Record the new IP
            table.create_entity({
                "PartitionKey": partition_key,
                "RowKey": ip_address
            })

            # Update main counter
            try:
                entity = table.get_entity(
                    partition_key=partition_key, row_key=row_key_counter)
                entity['count'] += 1
                table.update_entity(entity)
            except:
                entity = {'PartitionKey': partition_key,
                          'RowKey': row_key_counter, 'count': 1}
                table.create_entity(entity)

            return HttpResponse(f'{{"count": {entity["count"]}}}', mimetype="application/json")

    except Exception as e:
        return HttpResponse(f"Error: {str(e)}", status_code=500)
