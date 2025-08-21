import os
import unittest
from unittest.mock import patch, MagicMock, ANY
from datetime import datetime, timedelta
import azure.functions as func
from azure.core.exceptions import ResourceNotFoundError


import function_app


class TestUpdateCounter(unittest.TestCase):
    def setUp(self):
        """Set up mocks for each test."""
        os.environ['COSMOS_CONNECTION_STRING'] = 'UseDevelopmentStorage=true;'
        
        # Patch the TableServiceClient to avoid actual Azure calls
        self.patcher = patch('function_app.TableServiceClient')
        mock_TableServiceClient = self.patcher.start()
        mock_service = MagicMock()
        mock_TableServiceClient.from_connection_string.return_value = mock_service
        
        self.mock_table = MagicMock()
        mock_service.get_table_client.return_value = self.mock_table

    def tearDown(self):
        """Clean up patches after each test."""
        self.patcher.stop()
        if 'COSMOS_CONNECTION_STRING' in os.environ:
            del os.environ['COSMOS_CONNECTION_STRING']

    def test_first_visit_ever(self):
        """
        Tests the very first request to the function, where no counter or visitor exists.
        """
        ip = '1.2.3.5'
        # Simulate that neither the total counter nor the visitor IP entity exists
        self.mock_table.get_entity.side_effect = ResourceNotFoundError('Not found')

        req = func.HttpRequest('GET', '/api/updateCounter', headers={'x-forwarded-for': ip}, body=None)
        resp = function_app.update_counter(req)
        
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_body().decode(), '{"count": 1}')

        # Assert that the function created entities for both the counter and the new visitor
        self.mock_table.create_entity.assert_any_call(
            {'PartitionKey': function_app.PK_TOTAL, 'RowKey': function_app.RK_TOTAL, 'count': 1}
        )
        self.mock_table.create_entity.assert_any_call(
            {'PartitionKey': function_app.PK_VISITOR, 'RowKey': ip, 'lastVisit': ANY}
        )
        self.assertEqual(self.mock_table.create_entity.call_count, 2)

    def test_new_visitor_with_existing_counter(self):
        """
        Tests a new visitor IP when the main counter already exists.
        """
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

        # Assert that the new visitor IP was recorded
        self.mock_table.create_entity.assert_called_once_with(
            {'PartitionKey': function_app.PK_VISITOR, 'RowKey': ip, 'lastVisit': ANY}
        )
        # Assert that the main counter was updated
        self.mock_table.update_entity.assert_called_once()


    def test_visit_within_one_hour_does_not_increment(self):
        """
        Tests that a visit from an IP seen within the last hour does NOT increment the counter.
        """
        ip = '10.0.0.1'
        recent_time = (datetime.utcnow() - timedelta(minutes=30)).isoformat() + "Z"

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
        # The count should remain unchanged at 5
        self.assertEqual(resp.get_body().decode(), '{"count": 5}')

        # Assert that NO database write operations were called
        self.mock_table.create_entity.assert_not_called()
        self.mock_table.update_entity.assert_not_called()

    def test_visit_after_one_hour_increments_counter(self):
        """
        Tests that a visit from an IP seen more than an hour ago DOES increment the counter.
        """
        ip = '10.0.0.2'
        old_time = (datetime.utcnow() - timedelta(hours=2)).isoformat() + "Z"

        def get_entity_side_effect(partition_key, row_key):
            if partition_key == function_app.PK_TOTAL:
                return {'count': 20}
            if partition_key == function_app.PK_VISITOR:
                return {'lastVisit': old_time, 'PartitionKey': function_app.PK_VISITOR, 'RowKey': ip}
            return MagicMock()

        self.mock_table.get_entity.side_effect = get_entity_side_effect

        req = func.HttpRequest('GET', '/api/updateCounter', headers={'x-forwarded-for': ip}, body=None)
        resp = function_app.update_counter(req)
        
        self.assertEqual(resp.status_code, 200)
        # The count should increment to 21
        self.assertEqual(resp.get_body().decode(), '{"count": 21}')

        # Assert that both the total count and the visitor's timestamp were updated
        self.assertEqual(self.mock_table.update_entity.call_count, 2)
        self.mock_table.update_entity.assert_any_call(
            {'count': 21}, mode=ANY
        )
        self.mock_table.update_entity.assert_any_call(
            {'PartitionKey': function_app.PK_VISITOR, 'RowKey': ip, 'lastVisit': ANY}, mode=ANY
        )

    def test_options_request(self):
        """Tests a CORS preflight request."""
        req = func.HttpRequest('OPTIONS', '/api/updateCounter', headers={}, body=None)
        resp = function_app.update_counter(req)
        
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Access-Control-Allow-Origin', dict(resp.headers))

    def test_missing_connection_string(self):
        """Tests that the function fails gracefully if the connection string is missing."""
        del os.environ['COSMOS_CONNECTION_STRING']

        req = func.HttpRequest('GET', '/api/updateCounter', headers={'x-forwarded-for': '1.2.3.4'}, body=None)
        resp = function_app.update_counter(req)
        
        self.assertEqual(resp.status_code, 500)
        self.assertIn('Configuration error', resp.get_body().decode())

if __name__ == '__main__':
    unittest.main()