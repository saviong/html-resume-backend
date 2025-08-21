import unittest
import sys
import subprocess

try:
    import azure.functions as func
    from azure.core.exceptions import ResourceNotFoundError
    from unittest.mock import patch, MagicMock, ANY
    from datetime import datetime, timedelta
    import function_app
except ModuleNotFoundError as e:
    print("--- DIAGNOSTICS FROM WITHIN test.py ---")
    print(f"Caught Exception: {e}")
    print("\n[DEBUG] Python Executable:")
    print(sys.executable)
    print("\n[DEBUG] Python Version:")
    print(sys.version)
    print("\n[DEBUG] Python Path (where modules are searched):")
    for path in sys.path:
        print(path)
    
    print("\n[DEBUG] Running 'pip list' from within the test script...")
    subprocess.run([sys.executable, '-m', 'pip', 'list'])
    
    print("\n--- END DIAGNOSTICS ---")
    raise

class TestUpdateCounter(unittest.TestCase):
    def setUp(self):
        """Set up mocks for each test."""
        self.patcher = patch('function_app.TableServiceClient')
        mock_TableServiceClient = self.patcher.start()
        mock_service = MagicMock()
        mock_TableServiceClient.from_connection_string.return_value = mock_service
        self.mock_table = MagicMock()
        mock_service.get_table_client.return_value = self.mock_table

    def tearDown(self):
        """Clean up patches after each test."""
        self.patcher.stop()

    def test_first_visit_ever(self):
        ip = '1.2.3.5'
        self.mock_table.get_entity.side_effect = ResourceNotFoundError('Not found')
        req = func.HttpRequest('GET', '/api/updateCounter', headers={'x-forwarded-for': ip}, body=None)
        resp = function_app.update_counter(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_body().decode(), '{"count": 1}')
        self.mock_table.create_entity.assert_any_call(
            {'PartitionKey': function_app.PK_TOTAL, 'RowKey': function_app.RK_TOTAL, 'count': 1}
        )
        self.mock_table.create_entity.assert_any_call(
            {'PartitionKey': function_app.PK_VISITOR, 'RowKey': ip, 'lastVisit': ANY}
        )
