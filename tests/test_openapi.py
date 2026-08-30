"""OpenAPI backend: introspection filters to GET, validation is the spec's
own contract, execution binds path templates. All through a fake Transport."""

import json

import pytest

from queryglot.backends.openapi import OpenAPIBackend

SPEC = {
    "paths": {
        "/pet/findByStatus": {
            "get": {
                "operationId": "findPetsByStatus",
                "summary": "Finds pets by status",
                "parameters": [
                    {
                        "name": "status",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "string", "enum": ["available", "pending", "sold"]},
                    }
                ],
            }
        },
        "/pet/{petId}": {
            "get": {
                "operationId": "getPetById",
                "summary": "Find pet by ID",
                "parameters": [
                    {
                        "name": "petId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
            },
            "delete": {"operationId": "deletePet", "summary": "Deletes a pet"},
        },
        "/store/inventory": {
            "get": {"operationId": "getInventory", "summary": "Pet inventories by status"}
        },
        "/pet": {"post": {"operationId": "addPet", "summary": "Add a new pet"}},
        "/user/login": {
            "get": {
                "summary": "Logs user into the system",
                "parameters": [{"name": "username", "in": "query", "schema": {"type": "string"}}],
            }
        },
    }
}


class SpecTransport:
    """Serves SPEC at /openapi.json; records every other GET, returns canned data."""

    def __init__(self, data='{"ok": true}', status=200):
        self.data, self.status = data, status
        self.requests: list[str] = []

    def __call__(self, method, url, body, headers):
        assert method == "GET"
        if url.endswith("/openapi.json"):
            return 200, json.dumps(SPEC)
        self.requests.append(url)
        return self.status, self.data


@pytest.fixture
def backend():
    b = OpenAPIBackend("http://api.example/v3", transport=SpecTransport())
    b.introspect()
    return b


def test_introspects_only_get_operations():
    b = OpenAPIBackend("http://api.example/v3", transport=SpecTransport())
    items = b.introspect()
    names = {i.name for i in items}
    assert names == {"findPetsByStatus", "getPetById", "getInventory", "get_user_login"}
    assert "deletePet" not in names and "addPet" not in names  # absent, not guarded


def test_schema_item_shape():
    b = OpenAPIBackend("http://api.example/v3", transport=SpecTransport())
    by_name = {i.name: i for i in b.introspect()}
    item = by_name["findPetsByStatus"]
    assert item.backend == "openapi" and item.kind == "operation" and item.type == "GET"
    assert item.labels == ("status",)
    assert item.parent == "/pet/findByStatus"
    assert "status" in item.help.lower()


def test_missing_operation_id_gets_path_slug():
    b = OpenAPIBackend("http://api.example/v3", transport=SpecTransport())
    names = {i.name for i in b.introspect()}
    assert "get_user_login" in names


def test_unreachable_spec_raises_connection_error():
    def down(method, url, body, headers):
        return 503, "unavailable"

    with pytest.raises(ConnectionError):
        OpenAPIBackend("http://api.example/v3", transport=down).introspect()


def test_spec_without_paths_raises_connection_error():
    def empty(method, url, body, headers):
        return 200, "{}"

    with pytest.raises(ConnectionError):
        OpenAPIBackend("http://api.example/v3", transport=empty).introspect()


def call(op_id, **params):
    return json.dumps({"operationId": op_id, "parameters": params})


def test_valid_call_passes(backend):
    assert backend.validate(call("findPetsByStatus", status="available")).ok
    assert backend.validate(call("getInventory")).ok


def test_not_json_fails(backend):
    verdict = backend.validate("GET /pet/findByStatus")
    assert not verdict.ok and "JSON" in verdict.error


def test_unknown_operation_fails_with_catalog_message(backend):
    verdict = backend.validate(call("deletePet"))
    assert not verdict.ok
    assert "deletePet" in verdict.error and "catalog" in verdict.error


def test_missing_required_parameter_fails(backend):
    verdict = backend.validate(call("findPetsByStatus"))
    assert not verdict.ok and "status" in verdict.error and "required" in verdict.error


def test_unknown_parameter_fails(backend):
    verdict = backend.validate(call("getInventory", limit=5))
    assert not verdict.ok and "limit" in verdict.error


def test_wrong_type_fails(backend):
    verdict = backend.validate(call("getPetById", petId="five"))
    assert not verdict.ok and "petId" in verdict.error and "integer" in verdict.error


def test_enum_violation_fails(backend):
    verdict = backend.validate(call("findPetsByStatus", status="happy"))
    assert not verdict.ok and "available" in verdict.error


def test_bool_is_not_an_integer(backend):
    verdict = backend.validate(call("getPetById", petId=True))
    assert not verdict.ok


def test_execute_binds_path_and_query_params():
    transport = SpecTransport(data='[{"id": 1}]')
    b = OpenAPIBackend("http://api.example/v3", transport=transport)
    b.introspect()
    run = b.execute(call("getPetById", petId=5))
    assert run.ok and run.data == [{"id": 1}]
    assert transport.requests == ["http://api.example/v3/pet/5"]

    run = b.execute(call("findPetsByStatus", status="available"))
    assert run.ok
    assert transport.requests[-1] == "http://api.example/v3/pet/findByStatus?status=available"


def test_execute_url_encodes_path_params():
    transport = SpecTransport()
    b = OpenAPIBackend("http://api.example/v3", transport=transport)
    b.introspect()
    b.execute(call("getPetById", petId="a/b"))
    assert transport.requests == ["http://api.example/v3/pet/a%2Fb"]


def test_server_4xx_becomes_repair_fuel():
    b = OpenAPIBackend(
        "http://api.example/v3", transport=SpecTransport(data="Pet not found", status=404)
    )
    b.introspect()
    run = b.execute(call("getPetById", petId=99999))
    assert not run.ok and "404" in run.error and "Pet not found" in run.error


def test_non_json_2xx_body_is_returned_raw():
    b = OpenAPIBackend("http://api.example/v3", transport=SpecTransport(data="pong"))
    b.introspect()
    run = b.execute(call("getInventory"))
    assert run.ok and run.data == "pong"


def test_headers_are_sent_on_execute():
    seen = {}

    def spy(method, url, body, headers):
        if url.endswith("/openapi.json"):
            return 200, json.dumps(SPEC)
        seen.update(headers)
        return 200, "{}"

    b = OpenAPIBackend("http://api.example/v3", transport=spy, headers={"api_key": "k1"})
    b.introspect()
    b.execute(call("getInventory"))
    assert seen["api_key"] == "k1"
