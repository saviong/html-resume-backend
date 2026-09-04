import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import azure.functions as func
from azure.core.exceptions import (
    ResourceExistsError,
    ResourceModifiedError,
    ResourceNotFoundError,
)

import function_app


def entity(**fields):
    """A table entity that also carries an etag, as get_entity returns."""
    e = MagicMock(wraps=dict(fields))
    store = dict(fields)
    e.get = store.get
    e.__getitem__ = lambda _s, k: store[k]
    e.__setitem__ = lambda _s, k, v: store.__setitem__(k, v)
    e.metadata = {"etag": 'W/"etag"'}
    e.store = store
    return e


class TestUpdateCounter(unittest.TestCase):
    def setUp(self):
        os.environ["COSMOS_CONNECTION_STRING"] = (
            "DefaultEndpointsProtocol=https;AccountName=test;AccountKey=test;"
            "EndpointSuffix=core.windows.net"
        )
        function_app._table_client = None  # drop the client cached by earlier tests
        self.patcher = patch("function_app.TableServiceClient")
        mock_service_client = self.patcher.start()
        service = MagicMock()
        mock_service_client.from_connection_string.return_value = service
        self.mock_table = MagicMock()
        service.get_table_client.return_value = self.mock_table

    def tearDown(self):
        self.patcher.stop()
        function_app._table_client = None
        os.environ.pop("COSMOS_CONNECTION_STRING", None)
        os.environ.pop("ALLOWED_ORIGINS", None)

    def request(self, ip="1.2.3.4", method="GET", headers=None):
        h = {"x-forwarded-for": ip}
        h.update(headers or {})
        return func.HttpRequest(method, "/api/updateCounter", headers=h, body=None)

    def test_new_visitor_increments_existing_counter(self):
        self.mock_table.get_entity.return_value = entity(count=10)

        resp = function_app.update_counter(self.request("1.2.3.6"))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_body().decode(), '{"count": 11}')
        self.mock_table.create_entity.assert_called_once()
        self.mock_table.update_entity.assert_called_once()

    def test_first_ever_visit_creates_the_counter(self):
        self.mock_table.get_entity.side_effect = ResourceNotFoundError("no counter")

        resp = function_app.update_counter(self.request("1.2.3.7"))

        self.assertEqual(resp.get_body().decode(), '{"count": 1}')
        self.assertEqual(self.mock_table.create_entity.call_count, 2)  # visitor + counter

    def test_visit_within_one_hour_does_not_increment(self):
        ip = "10.0.0.1"
        recent = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        self.mock_table.create_entity.side_effect = ResourceExistsError()

        def get_entity(*args, **kwargs):
            pk = kwargs.get("partition_key", args[0] if args else None)
            if pk == function_app.PK_VISITOR:
                return entity(lastVisit=recent)
            return entity(count=5)

        self.mock_table.get_entity.side_effect = get_entity

        resp = function_app.update_counter(self.request(ip))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_body().decode(), '{"count": 5}')
        self.mock_table.update_entity.assert_not_called()

    def test_visit_after_one_hour_increments(self):
        stale = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        self.mock_table.create_entity.side_effect = ResourceExistsError()

        def get_entity(*args, **kwargs):
            pk = kwargs.get("partition_key", args[0] if args else None)
            if pk == function_app.PK_VISITOR:
                return entity(lastVisit=stale)
            return entity(count=7)

        self.mock_table.get_entity.side_effect = get_entity

        resp = function_app.update_counter(self.request("10.0.0.2"))

        self.assertEqual(resp.get_body().decode(), '{"count": 8}')

    def test_missing_last_visit_field_is_treated_as_new(self):
        """Previously crashed with a TypeError from fromisoformat(None) and returned 500."""
        self.mock_table.create_entity.side_effect = ResourceExistsError()

        def get_entity(*args, **kwargs):
            pk = kwargs.get("partition_key", args[0] if args else None)
            if pk == function_app.PK_VISITOR:
                return entity()  # legacy row with no lastVisit
            return entity(count=3)

        self.mock_table.get_entity.side_effect = get_entity

        resp = function_app.update_counter(self.request("10.0.0.3"))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_body().decode(), '{"count": 4}')

    def test_concurrent_increment_retries_instead_of_losing_a_count(self):
        """A racing writer bumps 5 -> 6; the retry must return 7, not 6."""
        totals = [entity(count=5), entity(count=6)]
        self.mock_table.get_entity.side_effect = lambda *a, **k: totals.pop(0)
        self.mock_table.update_entity.side_effect = [ResourceModifiedError("etag"), None]

        resp = function_app.update_counter(self.request("10.0.0.4"))

        self.assertEqual(resp.get_body().decode(), '{"count": 7}')
        self.assertEqual(self.mock_table.update_entity.call_count, 2)

    def test_client_cannot_spoof_its_ip_via_x_forwarded_for(self):
        """
        The leftmost x-forwarded-for entry is caller-supplied. Reading it let anyone
        inflate the counter by setting the header; only the edge-appended entry counts.
        """
        req = func.HttpRequest(
            "GET", "/api/updateCounter",
            headers={"x-forwarded-for": "203.0.113.77, 198.51.100.9:44321"}, body=None)
        self.assertEqual(function_app._get_ip(req), "198.51.100.9")

    def test_edge_header_wins_over_forwarded_for(self):
        req = func.HttpRequest(
            "GET", "/api/updateCounter",
            headers={"x-forwarded-for": "203.0.113.77",
                     "x-azure-clientip": "198.51.100.9"}, body=None)
        self.assertEqual(function_app._get_ip(req), "198.51.100.9")

    def test_ip_parsing_edge_cases(self):
        def ip(**h):
            return function_app._get_ip(
                func.HttpRequest("GET", "/api/updateCounter", headers=h, body=None))
        self.assertEqual(ip(**{"x-forwarded-for": "198.51.100.9:1234"}), "198.51.100.9")
        self.assertEqual(ip(**{"x-forwarded-for": "198.51.100.9"}), "198.51.100.9")
        # IPv6 has multiple colons and must not be truncated.
        self.assertEqual(ip(**{"x-forwarded-for": "2a0a:ef40::1"}), "2a0a:ef40::1")
        self.assertEqual(ip(), "unknown")

    def test_missing_connection_string_returns_500(self):
        del os.environ["COSMOS_CONNECTION_STRING"]

        resp = function_app.update_counter(self.request())

        self.assertEqual(resp.status_code, 500)

    def test_preflight_returns_204_with_cors_headers(self):
        resp = function_app.update_counter(self.request(method="OPTIONS"))

        self.assertEqual(resp.status_code, 204)
        self.assertEqual(resp.headers["Access-Control-Allow-Origin"], "*")
        self.assertIn("GET", resp.headers["Access-Control-Allow-Methods"])

    def test_origin_allowlist_echoes_only_allowed_origins(self):
        os.environ["ALLOWED_ORIGINS"] = "https://mycv.saviong.com"
        self.mock_table.get_entity.return_value = entity(count=1)

        allowed = function_app.update_counter(
            self.request(headers={"Origin": "https://mycv.saviong.com"})
        )
        self.assertEqual(
            allowed.headers["Access-Control-Allow-Origin"], "https://mycv.saviong.com"
        )

        function_app._table_client = None
        denied = function_app.update_counter(self.request(headers={"Origin": "https://evil.test"}))
        self.assertIsNone(denied.headers.get("Access-Control-Allow-Origin"))


if __name__ == "__main__":
    unittest.main()
