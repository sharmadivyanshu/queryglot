"""OpenAPI backend: introspection filters to GET, validation is the spec's
own contract, execution binds path templates. All through a fake Transport."""

import json

import pytest

from queryglot.backends.openapi import OpenAPIBackend
from queryglot.catalog import Catalog
from queryglot.graph import build_graph
from queryglot.prompts import FEWSHOT
from queryglot.retrieve import SchemaRetriever
from tests.conftest import ScriptedLLM

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
        "/pet/findByTags": {
            "get": {
                "operationId": "findPetsByTags",
                "summary": "Finds pets by tags",
                "parameters": [
                    {
                        "name": "tags",
                        "in": "query",
                        "schema": {"type": "array", "items": {"type": "string"}},
                    }
                ],
            }
        },
        "/pet/findByAvailability": {
            "get": {
                "operationId": "findPetsByAvailability",
                "summary": "Finds pets that are currently available",
                "parameters": [
                    {
                        "name": "onlyAvailable",
                        "in": "query",
                        "schema": {"type": "boolean"},
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


class CustomSpecTransport:
    """Serves an arbitrary spec at /openapi.json; records every other GET."""

    def __init__(self, spec, data='{"ok": true}', status=200):
        self.spec, self.data, self.status = spec, data, status
        self.requests: list[str] = []

    def __call__(self, method, url, body, headers):
        assert method == "GET"
        if url.endswith("/openapi.json"):
            return 200, json.dumps(self.spec)
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
    assert names == {
        "findPetsByStatus",
        "findPetsByTags",
        "findPetsByAvailability",
        "getPetById",
        "getInventory",
        "get_user_login",
    }
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


def test_execute_array_param_serializes_as_repeated_keys():
    transport = SpecTransport(data="[]")
    b = OpenAPIBackend("http://api.example/v3", transport=transport)
    b.introspect()
    b.execute(call("findPetsByTags", tags=["friendly", "calm"]))
    assert transport.requests == ["http://api.example/v3/pet/findByTags?tags=friendly&tags=calm"]


def test_execute_boolean_param_serializes_lowercase():
    transport = SpecTransport(data="[]")
    b = OpenAPIBackend("http://api.example/v3", transport=transport)
    b.introspect()
    b.execute(call("findPetsByAvailability", onlyAvailable=True))
    assert transport.requests == ["http://api.example/v3/pet/findByAvailability?onlyAvailable=true"]
    transport.requests.clear()
    b.execute(call("findPetsByAvailability", onlyAvailable=False))
    assert transport.requests == [
        "http://api.example/v3/pet/findByAvailability?onlyAvailable=false"
    ]


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


def test_fewshot_examples_exist_and_are_valid_calls():
    for line in FEWSHOT["openapi"].splitlines():
        if line.startswith("A: "):
            parsed = json.loads(line[3:])
            assert "operationId" in parsed and "parameters" in parsed


def test_graph_compiles_validates_and_executes_openapi_call():
    backend = OpenAPIBackend("http://api.example/v3", transport=SpecTransport(data='[{"id": 7}]'))
    catalog = Catalog()
    catalog.add(*backend.introspect())
    llm = ScriptedLLM(call("findPetsByStatus", status="available"))
    graph = build_graph(backend, SchemaRetriever(catalog), llm)
    final = graph.invoke({"question": "which pets are available by status?"})
    assert final["outcome"] == "answered"
    assert final["result"] == [{"id": 7}]


def test_graph_repairs_after_spec_violation():
    backend = OpenAPIBackend("http://api.example/v3", transport=SpecTransport())
    catalog = Catalog()
    catalog.add(*backend.introspect())
    llm = ScriptedLLM(
        call("findPetsByStatus", status="happy"),
        call("findPetsByStatus", status="available"),
    )
    graph = build_graph(backend, SchemaRetriever(catalog), llm)
    final = graph.invoke({"question": "which pets are available by status?"})
    assert final["outcome"] == "answered"
    assert "happy" in llm.calls[1]  # the invalid value, present only via the parser error


def test_mutating_request_abstains_because_operation_is_absent():
    backend = OpenAPIBackend("http://api.example/v3", transport=SpecTransport())
    catalog = Catalog()
    catalog.add(*backend.introspect())
    llm = ScriptedLLM("SHOULD_NEVER_RUN")
    graph = build_graph(backend, SchemaRetriever(catalog), llm)
    final = graph.invoke({"question": "remove every animal from storage"})
    assert final["outcome"] == "abstained"
    assert llm.calls == []


def test_path_item_parameters_merge_with_operation_parameters():
    spec = {
        "paths": {
            "/pet/{petId}": {
                "parameters": [
                    {
                        "name": "petId",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "integer"},
                    }
                ],
                "get": {"operationId": "getPetById2", "summary": "Find pet by ID"},
            }
        }
    }
    transport = CustomSpecTransport(spec, data='{"id": 5}')
    b = OpenAPIBackend("http://api.example/v3", transport=transport)
    items = b.introspect()
    assert len(items) == 1 and items[0].labels == ("petId",)

    assert not b.validate(call("getPetById2")).ok
    assert b.validate(call("getPetById2", petId=5)).ok

    run = b.execute(call("getPetById2", petId=5))
    assert run.ok and transport.requests == ["http://api.example/v3/pet/5"]


def test_operation_level_parameter_wins_over_path_level_on_collision():
    spec = {
        "paths": {
            "/pet/{petId}": {
                "parameters": [
                    {"name": "petId", "in": "path", "required": False, "schema": {"type": "string"}}
                ],
                "get": {
                    "operationId": "getPetById3",
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
            }
        }
    }
    b = OpenAPIBackend("http://api.example/v3", transport=CustomSpecTransport(spec))
    b.introspect()
    # operation-level wins: petId must be an integer, not the path-level string type
    verdict = b.validate(call("getPetById3", petId="five"))
    assert not verdict.ok and "integer" in verdict.error


def test_local_ref_parameter_resolves():
    spec = {
        "components": {
            "parameters": {
                "PetIdParam": {
                    "name": "petId",
                    "in": "path",
                    "required": True,
                    "schema": {"type": "integer"},
                }
            }
        },
        "paths": {
            "/pet/{petId}": {
                "get": {
                    "operationId": "getPetByIdRef",
                    "summary": "Find pet by ID via ref",
                    "parameters": [{"$ref": "#/components/parameters/PetIdParam"}],
                }
            },
            "/store/inventory": {"get": {"operationId": "getInventory2", "summary": "inventory"}},
        },
    }
    b = OpenAPIBackend("http://api.example/v3", transport=CustomSpecTransport(spec))
    items = b.introspect()
    names = {i.name for i in items}
    assert names == {"getPetByIdRef", "getInventory2"}
    item = next(i for i in items if i.name == "getPetByIdRef")
    assert item.labels == ("petId",)
    assert not b.validate(call("getPetByIdRef")).ok


def test_unresolvable_ref_parameter_skips_operation_but_not_rest_of_spec():
    spec = {
        "paths": {
            "/widget": {
                "get": {
                    "operationId": "getWidget",
                    "summary": "widget",
                    "parameters": [{"$ref": "external.yaml#/components/parameters/Foo"}],
                }
            },
            "/store/inventory": {"get": {"operationId": "getInventory3", "summary": "inventory"}},
        }
    }
    b = OpenAPIBackend("http://api.example/v3", transport=CustomSpecTransport(spec))
    items = b.introspect()
    names = {i.name for i in items}
    assert "getWidget" not in names
    assert "getInventory3" in names


def test_nested_unresolvable_ref_parameter_does_not_crash():
    spec = {
        "paths": {
            "/nested": {
                "get": {
                    "operationId": "getNested",
                    "summary": "nested",
                    "parameters": [{"$ref": "#/components/parameters/DoesNotExist"}],
                }
            },
            "/store/inventory": {"get": {"operationId": "getInventory4", "summary": "inventory"}},
        }
    }
    b = OpenAPIBackend("http://api.example/v3", transport=CustomSpecTransport(spec))
    items = b.introspect()
    names = {i.name for i in items}
    assert "getNested" not in names
    assert "getInventory4" in names


def test_public_export():
    import queryglot

    assert queryglot.OpenAPIBackend is OpenAPIBackend
    assert "OpenAPIBackend" in queryglot.__all__
