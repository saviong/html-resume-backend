import os
import unittest
from unittest.mock import patch, MagicMock, ANY
from datetime import datetime, timedelta, timezone # <-- IMPORT timezone
import azure.functions as func
from azure.core.exceptions import ResourceNotFoundError
import function_app

class TestUpdateCounter(unittest.TestCase):
    def setUp(self):
        os.environ['COSMOS_CONNECTION_STRING'] = 'DefaultEndpointsProtocol=https;AccountName=test;AccountKey=test;EndpointSuffix=core.windows.net'
        self.patcher = patch('function_app.TableServiceClient')
        mock_TableServiceClient = self.patcher.start()
        mock_service = MagicMock()
        mock_TableServiceClient.from_connection_string.return_value = mock_service
        self.mock_table = MagicMock()
        mock_service.get_table_client.return_value = self.mock_table

    def tearDown(self):
        self.patcher.stop()
        del os.environ['COSMOS_CONNECTION_STRING']

    def test_new_visitor_with_existing_counter(self):
        ip = '1.2.3.6'
        def get_entity_side_effect(partition_key, row_key):
            if partition_key == function_app.PK_TOTAL and row_key == function_app.RK_TOTAL:
                return {'PartitionKey': function_app.PK_TOTAL, 'RowKey': function_app.RK_TOTAL, 'count': 10}
            if partition_key == function_app.PK_VISITOR and row_key == ip:
                raise ResourceNotFoundError('Visitor IP not found')
            raise ValueError("Unexpected call to get_entity")

        self.mock_table.get_entity.side_effect = get_entity_side_effect
        req = func.HttpRequest('GET', '/api/updateCounter', headers={'x-forwarded-for': ip}, body=None)
        resp = function_app.update_counter(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_body().decode(), '{"count": 11}')

    def test_visit_within_one_hour_does_not_increment(self):
        ip = '10.0.0.1'
        recent_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        
        def get_entity_side_effect(partition_key, row_key):
            if partition_key == function_app.PK_TOTAL:
                return {'count': 5}
            if partition_key == function_app.PK_VISITOR:
                return {'lastVisit': recent_time}
            return MagicMock()

        self.mock_table.get_entity.side_effect = get_entity_side_effect
        req = func.HttpRequest('GET', '/api/updateCounter', headers={'x-forwarded-for': ip}, body=None)
        resp = function_app.update_counter(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_body().decode(), '{"count": 5}')
        self.mock_table.create_entity.assert_not_called()
        self.mock_table.update_entity.assert_not_called()

if __name__ == '__main__':
    unittest.main()