"""queryglot — one question, many query languages.

Schema-aware natural-language search over observability backends, shipped as
an MCP server. Retrieval supplies YOUR schema (the part no model can know);
the model supplies syntax (the part a small fine-tune learns); the backend's
own parser has the final word.
"""

from .backends.elastic import ElasticBackend
from .backends.openapi import OpenAPIBackend
from .backends.prometheus import PrometheusBackend
from .catalog import Catalog, SchemaItem
from .engine import Answer, Engine
from .llm import LLM, OpenAICompatibleLLM
from .retrieve import SchemaRetriever

__version__ = "0.1.0"

__all__ = [
    "Answer",
    "Catalog",
    "ElasticBackend",
    "Engine",
    "LLM",
    "OpenAICompatibleLLM",
    "OpenAPIBackend",
    "PrometheusBackend",
    "SchemaItem",
    "SchemaRetriever",
]
