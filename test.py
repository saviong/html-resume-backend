import unittest
from unittest.mock import patch, MagicMock
from function_app import main
from azure.functions import HttpRequest


class TestVisitorCounter(unittest.TestCase):
    @patch("function_app.TableServiceClient")
    @patch("function_app.os.environ", {"COSMOS_CONNECTION_STRING": "fake-connection-string"})
    def test_counter_increment_existing(self, mock_table_service):
        mock_table_client = MagicMock()
        mock_entity = {'PartitionKey': 'counter',
                       'RowKey': 'visits', 'count': 5}

        mock_table_client.get_entity.return_value = mock_entity
        mock_table_service.from_connection_string.return_value.get_table_client.return_value = mock_table_client

        req = HttpRequest(
            method="GET",
            url="/api/updateCounter",
            body=None,
            headers={"x-forwarded-for": "123.45.67.89"}  # ✅ Added header
        )

        response = main(req)
        self.assertEqual(response.status_code, 200)
        self.assertIn('"count": 6', response.get_body().decode())

    @patch("function_app.TableServiceClient")
    @patch("function_app.os.environ", {"COSMOS_CONNECTION_STRING": "fake-connection-string"})
    def test_counter_create_new(self, mock_table_service):
        mock_table_client = MagicMock()
        mock_table_client.get_entity.side_effect = Exception(
            "Entity not found")
        mock_table_service.from_connection_string.return_value.get_table_client.return_value = mock_table_client

        req = HttpRequest(
            method="GET",
            url="/api/updateCounter",
            body=None,
            headers={"x-forwarded-for": "98.76.54.32"}  # ✅ Added header
        )

        response = main(req)
        self.assertEqual(response.status_code, 200)
        self.assertIn('"count": 1', response.get_body().decode())


if __name__ == '__main__':
    unittest.main()
