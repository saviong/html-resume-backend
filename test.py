import os
import unittest
from unittest.mock import patch, MagicMock
import azure.functions as func
from azure.core.exceptions import ResourceNotFoundError
import function_app


class TestUpdateCounter(unittest.TestCase):
    def setUp(self):
        # Ensure the connection string env var is set
        os.environ['COSMOS_CONNECTION_STRING'] = 'UseDevelopmentStorage=true;'

        # Patch TableServiceClient.from_connection_string to return a mock service
        self.patcher = patch('function_app.TableServiceClient')
        self.mock_TableServiceClient = self.patcher.start()
        self.mock_service = MagicMock()
        self.mock_TableServiceClient.from_connection_string.return_value = self.mock_service

        # Patch get_table_client to return a mock table client
        self.mock_table = MagicMock()
        self.mock_service.get_table_client.return_value = self.mock_table

    def tearDown(self):
        self.patcher.stop()
        del os.environ['COSMOS_CONNECTION_STRING']

    def test_no_ip_header(self):
        req = func.HttpRequest(
            'GET', '/api/updateCounter', headers={}, body=None)
        resp = function_app.main(req)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_body().decode(), "IP address not found")

    def test_existing_ip(self):
        ip = '1.2.3.4'
        # First get_entity(ip) returns something (means IP seen), then get_entity(counter) returns count
        self.mock_table.get_entity.side_effect = [
            {'PartitionKey': 'counter', 'RowKey': ip},  # dummy entity for IP
            {'count': 5}                                # counter entity
        ]

        req = func.HttpRequest('GET', '/api/updateCounter',
                               headers={'x-forwarded-for': ip}, body=None)
        resp = function_app.main(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, 'application/json')
        self.assertEqual(resp.get_body().decode(), '{"count": 5}')

    def test_new_ip_and_first_counter(self):
        ip = '1.2.3.5'
        # Simulate both entities not found
        self.mock_table.get_entity.side_effect = ResourceNotFoundError(
            'Not found')

        req = func.HttpRequest('GET', '/api/updateCounter',
                               headers={'x-forwarded-for': ip}, body=None)
        resp = function_app.main(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_body().decode(), '{"count": 1}')

        # Should create two entities: one for the IP, one for the counter
        self.assertEqual(self.mock_table.create_entity.call_count, 2)

    def test_new_ip_and_increment_counter(self):
        ip = '1.2.3.6'
        # Raise on IP lookup, succeed on counter lookup

        def get_entity_side_effect(partition_key, row_key):
            if row_key == ip:
                raise ResourceNotFoundError('IP not found')
            elif row_key == 'visits':
                return {'PartitionKey': 'counter', 'RowKey': 'visits', 'count': 10}
            raise ResourceNotFoundError('Unknown')

        self.mock_table.get_entity.side_effect = get_entity_side_effect

        req = func.HttpRequest('GET', '/api/updateCounter',
                               headers={'x-forwarded-for': ip}, body=None)
        resp = function_app.main(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_body().decode(), '{"count": 11}')

        # Check that we recorded the new IP
        self.mock_table.create_entity.assert_any_call({
            'PartitionKey': 'counter',
            'RowKey': ip
        })
        # And that we updated the counter entity
        self.mock_table.update_entity.assert_called_with({
            'PartitionKey': 'counter',
            'RowKey': 'visits',
            'count': 11
        })


if __name__ == '__main__':
    unittest.main()
