"""Integration against a real Swagger Petstore (swaggerapi/petstore3).

Skipped unless QUERYGLOT_TEST_PETSTORE is set (API root, e.g.
http://localhost:8081/api/v3) — skips are visible, never silent passes.
"""

import json
import os

import pytest

PETSTORE = os.getenv("QUERYGLOT_TEST_PETSTORE")
pytestmark = pytest.mark.skipif(not PETSTORE, reason="set QUERYGLOT_TEST_PETSTORE to run")

from queryglot import OpenAPIBackend  # noqa: E402


@pytest.fixture(scope="module")
def backend():
    b = OpenAPIBackend(PETSTORE)
    b.introspect()
    return b


def test_real_spec_introspects_get_only(backend):
    items = backend.introspect()
    names = {i.name for i in items}
    assert len(names) > 5
    assert "findPetsByStatus" in names and "getInventory" in names
    assert "addPet" not in names and "deletePet" not in names


def test_real_validate_and_execute_roundtrip(backend):
    query = json.dumps({"operationId": "findPetsByStatus", "parameters": {"status": "available"}})
    assert backend.validate(query).ok
    run = backend.execute(query)
    assert run.ok and isinstance(run.data, list)


def test_real_server_error_feeds_repair(backend):
    query = json.dumps({"operationId": "getPetById", "parameters": {"petId": 999999999}})
    assert backend.validate(query).ok  # spec-valid…
    run = backend.execute(query)
    assert not run.ok  # …but the server has the final word
