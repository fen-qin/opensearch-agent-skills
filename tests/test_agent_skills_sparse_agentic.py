"""Tests for sparse vs dense agentic flow agent logic.

Validates:
- FlowAgentBuilder subclass dispatching (sparse vs dense)
- SparseFlowAgentBuilder tool configuration
- DenseFlowAgentBuilder tool configuration
- _introspect_search_config correctly detects sparse agentic from _meta
- _search_sparse_agentic parses NeuralSparseSearchTool output
- _parse_sparse_tool_results handles various output formats
- create_flow_agentic_pipeline branches correctly on is_sparse
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add agent skills scripts to path
sys.path.insert(
    0, str(Path(__file__).resolve().parents[1] / "skills" / "opensearch-skills" / "scripts")
)

from lib.operations import (
    DenseFlowAgentBuilder,
    FlowAgentBuilder,
    SparseFlowAgentBuilder,
    create_flow_agent,
    create_flow_agentic_pipeline,
)
from lib.search import (
    _parse_sparse_tool_results,
    _generate_rag_summary,
    _search_sparse_agentic,
)


# ---------------------------------------------------------------------------
# FlowAgentBuilder subclass tests
# ---------------------------------------------------------------------------


class TestDenseFlowAgentBuilder:
    def test_build_tools_with_embedding_model(self):
        client = MagicMock()
        builder = DenseFlowAgentBuilder(
            client, "test-agent", "llm-model-id", "embedding-model-id", "my-index"
        )
        tools = builder.build_tools()

        assert len(tools) == 2
        assert tools[0]["type"] == "IndexMappingTool"
        assert tools[1]["type"] == "QueryPlanningTool"
        assert tools[1]["parameters"]["model_id"] == "llm-model-id"
        assert tools[1]["parameters"]["embedding_model_id"] == "embedding-model-id"

    def test_build_tools_without_embedding_model(self):
        client = MagicMock()
        builder = DenseFlowAgentBuilder(
            client, "test-agent", "llm-model-id", "", "my-index"
        )
        tools = builder.build_tools()

        assert len(tools) == 2
        assert "embedding_model_id" not in tools[1]["parameters"]

    def test_create_registers_agent(self):
        client = MagicMock()
        client.transport.perform_request.return_value = {"agent_id": "abc123"}
        builder = DenseFlowAgentBuilder(
            client, "my-agent", "llm-id", "embed-id", "idx"
        )
        result = builder.create()

        assert "abc123" in result
        call_args = client.transport.perform_request.call_args
        assert call_args[0][0] == "POST"
        assert "/_plugins/_ml/agents/_register" in call_args[0][1]
        body = call_args[1]["body"] if "body" in call_args[1] else call_args[0][2]
        assert body["type"] == "flow"


class TestSparseFlowAgentBuilder:
    def test_build_tools_uses_neural_sparse_search_tool(self):
        client = MagicMock()
        client.indices.get_mapping.return_value = {
            "my-index": {
                "mappings": {
                    "properties": {
                        "text": {"type": "text"},
                        "text_sparse": {"type": "rank_features"},
                        "headings": {"type": "keyword"},
                        "chunk_id": {"type": "integer"},
                    }
                }
            }
        }
        builder = SparseFlowAgentBuilder(
            client, "sparse-agent", "llm-id", "sparse-tokenizer-id", "my-index"
        )
        tools = builder.build_tools()

        assert len(tools) == 1
        assert tools[0]["type"] == "NeuralSparseSearchTool"
        params = tools[0]["parameters"]
        assert params["index"] == "my-index"
        assert params["embedding_field"] == "text_sparse"
        assert params["model_id"] == "sparse-tokenizer-id"
        # source_field is JSON-encoded list of non-vector fields
        source_field = params["source_field"]
        import json as _json
        source_fields = _json.loads(source_field)
        assert "text" in source_fields
        assert "headings" in source_fields
        assert "text_sparse" not in source_fields

    def test_detect_sparse_field_finds_rank_features(self):
        client = MagicMock()
        client.indices.get_mapping.return_value = {
            "my-index": {
                "mappings": {
                    "properties": {
                        "content": {"type": "text"},
                        "content_embedding": {"type": "rank_features"},
                    }
                }
            }
        }
        builder = SparseFlowAgentBuilder(
            client, "agent", "llm-id", "sparse-id", "my-index"
        )
        sparse_field = builder._detect_sparse_field()
        assert sparse_field == "content_embedding"

    def test_detect_sparse_field_fallback(self):
        client = MagicMock()
        client.indices.get_mapping.side_effect = Exception("not found")
        builder = SparseFlowAgentBuilder(
            client, "agent", "llm-id", "sparse-id", "my-index"
        )
        sparse_field = builder._detect_sparse_field()
        assert sparse_field == "text_sparse"

    def test_description_is_sparse(self):
        client = MagicMock()
        builder = SparseFlowAgentBuilder(
            client, "agent", "llm-id", "sparse-id", "my-index"
        )
        assert "sparse" in builder.description()


# ---------------------------------------------------------------------------
# create_flow_agent dispatcher tests
# ---------------------------------------------------------------------------


class TestCreateFlowAgent:
    def test_sparse_requires_index(self):
        result = create_flow_agent("agent", "llm-id", "embed-id", index_name="", is_sparse=True)
        assert "Error" in result
        assert "--index" in result

    def test_requires_model_id(self):
        result = create_flow_agent("agent", "", "embed-id", index_name="idx", is_sparse=False)
        assert "Error" in result

    @patch("lib.operations.create_client")
    def test_dispatches_to_sparse_builder(self, mock_create_client):
        client = MagicMock()
        mock_create_client.return_value = client
        client.indices.get_mapping.return_value = {
            "idx": {"mappings": {"properties": {"text": {"type": "text"}, "text_sparse": {"type": "rank_features"}}}}
        }
        client.transport.perform_request.return_value = {"agent_id": "sparse-agent-id"}

        result = create_flow_agent("agent", "llm-id", "sparse-tok", index_name="idx", is_sparse=True)

        assert "sparse-agent-id" in result
        body = client.transport.perform_request.call_args[1]["body"] if "body" in client.transport.perform_request.call_args[1] else client.transport.perform_request.call_args[0][2]
        assert body["tools"][0]["type"] == "NeuralSparseSearchTool"

    @patch("lib.operations.create_client")
    def test_dispatches_to_dense_builder(self, mock_create_client):
        client = MagicMock()
        mock_create_client.return_value = client
        client.transport.perform_request.return_value = {"agent_id": "dense-agent-id"}

        result = create_flow_agent("agent", "llm-id", "embed-id", index_name="idx", is_sparse=False)

        assert "dense-agent-id" in result
        body = client.transport.perform_request.call_args[1]["body"] if "body" in client.transport.perform_request.call_args[1] else client.transport.perform_request.call_args[0][2]
        assert body["tools"][0]["type"] == "IndexMappingTool"
        assert body["tools"][1]["type"] == "QueryPlanningTool"


# ---------------------------------------------------------------------------
# create_flow_agentic_pipeline tests
# ---------------------------------------------------------------------------


class TestCreateFlowAgenticPipeline:
    @patch("lib.operations.create_client")
    def test_sparse_stores_meta(self, mock_create_client):
        client = MagicMock()
        mock_create_client.return_value = client

        result = create_flow_agentic_pipeline(
            "pipeline", "agent-123", "my-index",
            is_sparse=True, agentic_model_id="llm-id",
        )

        assert "Sparse agentic config" in result
        # Should store in _meta
        client.indices.put_mapping.assert_called_once()
        mapping_body = client.indices.put_mapping.call_args[1]["body"]
        assert mapping_body["_meta"]["agentic_agent_id"] == "agent-123"
        assert mapping_body["_meta"]["agentic_type"] == "sparse"
        assert mapping_body["_meta"]["agentic_model_id"] == "llm-id"

    @patch("lib.operations.create_client")
    def test_sparse_clears_search_pipeline(self, mock_create_client):
        client = MagicMock()
        mock_create_client.return_value = client

        create_flow_agentic_pipeline(
            "pipeline", "agent-123", "my-index", is_sparse=True,
        )

        # Should set search pipeline to _none
        client.indices.put_settings.assert_called_once()
        settings_body = client.indices.put_settings.call_args[1]["body"]
        assert settings_body["index"]["search.default_pipeline"] == "_none"

    @patch("lib.operations.create_client")
    def test_dense_creates_pipeline(self, mock_create_client):
        client = MagicMock()
        mock_create_client.return_value = client

        result = create_flow_agentic_pipeline(
            "my-pipeline", "agent-456", "my-index",
            embedding_model_id="embed-id", is_sparse=False,
        )

        assert "attached" in result
        # Should create search pipeline via PUT
        put_call = client.transport.perform_request.call_args
        assert "/_search/pipeline/my-pipeline" in put_call[0][1]
        pipeline_body = put_call[1]["body"] if "body" in put_call[1] else put_call[0][2]
        assert pipeline_body["request_processors"][0]["agentic_query_translator"]["agent_id"] == "agent-456"
        assert pipeline_body["request_processors"][1]["neural_query_enricher"]["default_model_id"] == "embed-id"

    def test_requires_agent_id_and_index(self):
        result = create_flow_agentic_pipeline("p", "", "idx")
        assert "Error" in result
        result = create_flow_agentic_pipeline("p", "agent", "")
        assert "Error" in result


# ---------------------------------------------------------------------------
# _parse_sparse_tool_results tests
# ---------------------------------------------------------------------------


class TestParseSparseToolResults:
    def test_parses_newline_delimited_json(self):
        raw = (
            '{"_index":"idx","_id":"1","_score":5.5,"_source":{"text":"hello","headings":["H1"]}}\n'
            '{"_index":"idx","_id":"2","_score":3.2,"_source":{"text":"world"}}\n'
        )
        hits = _parse_sparse_tool_results(raw)

        assert len(hits) == 2
        assert hits[0]["id"] == "1"
        assert hits[0]["score"] == 5.5
        assert hits[0]["source"]["text"] == "hello"
        assert hits[1]["id"] == "2"
        assert hits[1]["score"] == 3.2

    def test_parses_json_array(self):
        raw = json.dumps([
            {"_id": "a", "_score": 2.0, "_source": {"text": "doc a"}},
            {"_id": "b", "_score": 1.5, "_source": {"text": "doc b"}},
        ])
        hits = _parse_sparse_tool_results(raw)

        assert len(hits) == 2
        assert hits[0]["id"] == "a"
        assert hits[1]["id"] == "b"

    def test_strips_vector_fields(self):
        # _is_vector_value requires >= 4 tokens to detect sparse vectors
        raw = '{"_id":"1","_score":1.0,"_source":{"text":"hi","text_sparse":{"token1":0.5,"token2":0.3,"token3":0.2,"token4":0.1}}}\n'
        hits = _parse_sparse_tool_results(raw)

        assert len(hits) == 1
        assert "text_sparse" not in hits[0]["source"]
        assert hits[0]["source"]["text"] == "hi"

    def test_empty_input(self):
        assert _parse_sparse_tool_results("") == []
        assert _parse_sparse_tool_results("   ") == []

    def test_invalid_json_skipped(self):
        raw = "not json\n{\"_id\":\"1\",\"_score\":1.0,\"_source\":{\"text\":\"ok\"}}\ngarbage\n"
        hits = _parse_sparse_tool_results(raw)

        assert len(hits) == 1
        assert hits[0]["id"] == "1"


# ---------------------------------------------------------------------------
# _search_sparse_agentic tests
# ---------------------------------------------------------------------------


class TestSearchSparseAgentic:
    def test_returns_error_when_no_agent_id(self):
        client = MagicMock()
        config = {"agentic_agent_id": "", "agentic_model_id": "", "lexical_fields": ["*"]}
        result = _search_sparse_agentic(client, "idx", "query", 10, config)

        assert result["error"]
        assert "agent_id" in result["error"]

    def test_calls_agent_execute(self):
        client = MagicMock()
        client.transport.perform_request.return_value = {
            "inference_results": [{
                "output": [{
                    "name": "response",
                    "result": '{"_index":"idx","_id":"1","_score":5.0,"_source":{"text":"result doc"}}'
                }]
            }]
        }
        config = {
            "agentic_agent_id": "my-agent-id",
            "agentic_model_id": "",
            "lexical_fields": ["*"],
        }
        result = _search_sparse_agentic(client, "idx", "test query", 10, config)

        assert result["error"] == ""
        assert result["query_mode"] == "agentic"
        assert result["capability"] == "agentic_flow"
        assert result["used_semantic"] is True
        assert len(result["hits"]) == 1
        assert result["hits"][0]["id"] == "1"
        assert result["hits"][0]["score"] == 5.0

        # Verify the agent was called correctly
        call_args = client.transport.perform_request.call_args
        assert "/_plugins/_ml/agents/my-agent-id/_execute" in call_args[0][1]
        body = call_args[1]["body"] if "body" in call_args[1] else call_args[0][2]
        assert body["parameters"]["input"] == "test query"

    def test_falls_back_to_bm25_on_agent_failure(self):
        client = MagicMock()
        client.transport.perform_request.side_effect = Exception("agent timeout")
        client.search.return_value = {
            "hits": {"total": {"value": 1}, "hits": [
                {"_id": "fb1", "_score": 1.0, "_source": {"text": "fallback"}}
            ]},
            "took": 5,
        }
        config = {
            "agentic_agent_id": "my-agent",
            "agentic_model_id": "",
            "lexical_fields": ["text"],
        }
        result = _search_sparse_agentic(client, "idx", "query", 10, config)

        assert "agent execution failed" in result["fallback_reason"]
        assert result["query_mode"] == "agentic_fallback_bm25"
        assert len(result["hits"]) == 1


# ---------------------------------------------------------------------------
# _generate_rag_summary tests
# ---------------------------------------------------------------------------


class TestGenerateRagSummary:
    def test_generates_summary_from_hits(self):
        client = MagicMock()
        client.transport.perform_request.return_value = {
            "inference_results": [{
                "output": [{
                    "dataAsMap": {
                        "output": {
                            "message": {
                                "content": [{"text": "Here is a summary of results."}],
                                "role": "assistant",
                            }
                        }
                    }
                }]
            }]
        }
        hits = [
            {"source": {"text": "document about engines", "headings": ["Motors"]}},
            {"source": {"text": "brake maintenance guide"}},
        ]
        result = _generate_rag_summary(client, "model-123", "how to fix engine", hits)

        assert result == "Here is a summary of results."
        call_args = client.transport.perform_request.call_args
        assert "/_plugins/_ml/models/model-123/_predict" in call_args[0][1]

    def test_returns_empty_on_failure(self):
        client = MagicMock()
        client.transport.perform_request.side_effect = Exception("model error")

        result = _generate_rag_summary(client, "model-123", "query", [{"source": {"text": "x"}}])
        assert result == ""


# ---------------------------------------------------------------------------
# Introspection: _meta detection tests
# ---------------------------------------------------------------------------


class TestIntrospectSparseAgentic:
    """Test that _introspect_search_config detects sparse agentic from _meta."""

    @patch("lib.search.extract_index_field_specs")
    @patch("lib.search._resolve_semantic_runtime_hints")
    def test_sparse_meta_sets_strategy_and_fields(self, mock_hints, mock_fields):
        from lib.search import _introspect_search_config

        mock_fields.return_value = {
            "text": {"type": "text"},
            "text_sparse": {"type": "rank_features"},
        }
        mock_hints.return_value = {
            "vector_field": "text_sparse",
            "model_id": "sparse-model",
            "default_pipeline": "ingest-pipe",
            "search_pipeline": "",
            "has_agentic_pipeline": "false",
            "has_neural_search_pipeline": "false",
            "has_sparse": "true",
            "has_rag_processor": "false",
            "rag_model_id": "",
            "agentic_model_id": "llm-model-id",
            "agentic_agent_type": "",
            "agentic_embedding_type": "sparse",
            "agentic_agent_id": "my-sparse-agent",
        }

        client = MagicMock()
        config = _introspect_search_config(client, "my-index")

        assert config["strategy"] == "agentic_flow"
        assert config["agentic_embedding_type"] == "sparse"
        assert config["agentic_agent_id"] == "my-sparse-agent"
        assert config["agentic_model_id"] == "llm-model-id"

    @patch("lib.search.extract_index_field_specs")
    @patch("lib.search._resolve_semantic_runtime_hints")
    def test_dense_pipeline_sets_dense_embedding_type(self, mock_hints, mock_fields):
        from lib.search import _introspect_search_config

        mock_fields.return_value = {
            "text": {"type": "text"},
            "embedding": {"type": "knn_vector"},
        }
        mock_hints.return_value = {
            "vector_field": "embedding",
            "model_id": "dense-model",
            "default_pipeline": "",
            "search_pipeline": "my-search-pipe",
            "has_agentic_pipeline": "true",
            "has_neural_search_pipeline": "false",
            "has_sparse": "false",
            "has_rag_processor": "false",
            "rag_model_id": "",
            "agentic_model_id": "llm-id",
            "agentic_agent_type": "flow",
            "agentic_embedding_type": "",
            "agentic_agent_id": "",
        }

        client = MagicMock()
        config = _introspect_search_config(client, "my-index")

        assert config["strategy"] == "agentic_flow"
        assert config["agentic_embedding_type"] == "dense"

    @patch("lib.search.extract_index_field_specs")
    @patch("lib.search._resolve_semantic_runtime_hints")
    def test_no_agentic_stays_bm25(self, mock_hints, mock_fields):
        from lib.search import _introspect_search_config

        mock_fields.return_value = {"text": {"type": "text"}}
        mock_hints.return_value = {
            "vector_field": "",
            "model_id": "",
            "default_pipeline": "",
            "search_pipeline": "",
            "has_agentic_pipeline": "false",
            "has_neural_search_pipeline": "false",
            "has_sparse": "false",
            "has_rag_processor": "false",
            "rag_model_id": "",
            "agentic_model_id": "",
            "agentic_agent_type": "",
            "agentic_embedding_type": "",
            "agentic_agent_id": "",
        }

        client = MagicMock()
        config = _introspect_search_config(client, "my-index")

        assert config["strategy"] == "bm25"
        assert config["agentic_embedding_type"] == ""
