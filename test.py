import os
import unittest
from unittest.mock import patch, MagicMock, ANY
from datetime import datetime, timedelta, timezone
import azure.functions as func
from azure.core.exceptions import ResourceNotFoundError, ResourceExistsError
import function_app

class TestUpdateCounter(unittest.TestCase):
    def setUp(self):
        """Set up mocks and environment variables for each test."""
        os.environ['COSMOS_CONNECTION_STRING'] = 'DefaultEndpointsProtocol=https;AccountName=test;AccountKey=test;EndpointSuffix=core.windows.net'
        self.patcher = patch('function_app.TableServiceClient')
        mock_TableServiceClient = self.patcher.start()
        mock_service = MagicMock()
        mock_TableServiceClient.from_connection_string.return_value = mock_service
        self.mock_table = MagicMock()
        mock_service.get_table_client.return_value = self.mock_table

    def tearDown(self):
        """Clean up patches and environment variables after each test."""
        self.patcher.stop()
        del os.environ['COSMOS_CONNECTION_STRING']

    def test_new_visitor_with_existing_counter(self):
        """Tests a new visitor where the counter already exists."""
        ip = '1.2.3.6'
        
        # In this scenario, create_entity should succeed.
        # get_entity will only be called for the total counter.
        self.mock_table.get_entity.return_value = {'count': 10}

        req = func.HttpRequest('GET', '/api/updateCounter', headers={'x-forwarded-for': ip}, body=None)
        resp = function_app.update_counter(req)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_body().decode(), '{"count": 11}')
        # Assert that the new IP record was created.
        self.mock_table.create_entity.assert_called_once()
        # Assert that the total counter was updated.
        self.mock_table.update_entity.assert_called_once()

    def test_visit_within_one_hour_does_not_increment(self):
        """
        Tests that a visit from an IP seen within the last hour does NOT increment the counter.
        """
        ip = '10.0.0.1'
        recent_time = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()

        # 1. Mock create_entity to fail by raising ResourceExistsError,
        #    simulating that the IP record already exists.
        self.mock_table.create_entity.side_effect = ResourceExistsError()

        # 2. Mock get_entity to return the existing records when the function
        #    checks for the timestamp and the total.
        def get_entity_side_effect(partition_key, row_key):
            if partition_key == function_app.PK_VISITOR and row_key == ip:
                return {'lastVisit': recent_time} # The existing visitor record
            if partition_key == function_app.PK_TOTAL:
                return {'count': 5} # The current total
            # This is the line with the typo
            raise ResourceNotFoundError("Entity not found in mock")

        self.mock_table.get_entity.side_effect = get_entity_side_effect

        req = func.HttpRequest('GET', '/api/updateCounter', headers={'x-forwarded-for': ip}, body=None)
        resp = function_app.update_counter(req)

        # Assert that the function correctly returned 200 OK and the UNCHANGED count of 5
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_body().decode(), '{"count": 5}')
        # Assert that no NEW entity was created and the total was NOT updated.
        self.mock_table.update_entity.assert_not_called()


if __name__ == '__main__':
    unittest.main()