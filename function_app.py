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
        row_key = "visits"

        try:
            entity = table.get_entity(
                partition_key=partition_key, row_key=row_key)
            entity['count'] += 1
            table.update_entity(entity)
        except:
            entity = {'PartitionKey': partition_key,
                      'RowKey': row_key, 'count': 1}
            table.create_entity(entity)

        return HttpResponse(f'{{"count": {entity["count"]}}}', mimetype="application/json")

    except Exception as e:
        return HttpResponse(f"Error: {str(e)}", status_code=500)
