from __future__ import annotations

from types import SimpleNamespace

from rag.ingestion.config import (
    BackendConfig,
    MinioConfig,
    MockSwitches,
    ModelProviderConfig,
    QdrantConfig,
    VisionConfig,
    WorkerConfig,
)
from rag.ingestion.adapters import vision as vision_module
from rag.ingestion.adapters.vision import OLLAMA_PROVIDER, VisionClient
from rag.ingestion.parsers.images import _image_item_text
from rag.ingestion.execution import _build_vision_client


def test_ollama_runtime_config_routes_vision_to_ollama() -> None:
    client = _build_vision_client(
        _worker_config(),
        SimpleNamespace(
            provider="ollama",
            base_url="http://ollama:11434",
            ingestion_base_url="http://ollama-ingest:11434",
            chat_model="qwen3.5:27b",
            ingestion_model="llava:latest",
            vision_model=None,
        ),
    )

    assert client.provider == OLLAMA_PROVIDER
    assert client.base_url == "http://ollama-ingest:11434"
    assert client.model == "llava:latest"
    assert client.num_ctx == 8192


def test_ollama_runtime_config_prefers_saved_vision_model() -> None:
    config = _worker_config(ollama_vision_model="llava-env:latest")
    client = _build_vision_client(
        config,
        SimpleNamespace(
            provider="ollama",
            base_url="http://ollama:11434",
            ingestion_base_url="http://ollama-ingest:11434",
            chat_model="qwen3.5:27b",
            ingestion_model="qwen3.5:27b",
            vision_model="qwen3.5-vl:2b",
        ),
    )

    assert client.provider == OLLAMA_PROVIDER
    assert client.model == "qwen3.5-vl:2b"


def test_ollama_runtime_config_uses_env_vision_fallback() -> None:
    config = _worker_config(ollama_vision_model="qwen3.5-vl:2b")
    client = _build_vision_client(
        config,
        SimpleNamespace(
            provider="ollama",
            base_url="http://ollama:11434",
            ingestion_base_url="http://ollama-ingest:11434",
            chat_model="qwen3.5:27b",
            ingestion_model="qwen3.5:27b",
            vision_model=None,
        ),
    )

    assert client.provider == OLLAMA_PROVIDER
    assert client.model == "qwen3.5-vl:2b"


def test_vllm_runtime_config_keeps_openai_compatible_vision_endpoint() -> None:
    client = _build_vision_client(
        _worker_config(),
        SimpleNamespace(provider="vllm", base_url="http://vllm-text:8000/v1"),
    )

    assert client.provider == "openai_compatible"
    assert client.base_url == "http://vllm-vision:8000/v1"
    assert client.model == "Qwen/Qwen2.5-VL-7B-Instruct-AWQ"


def test_mixed_runtime_config_can_route_vision_to_ollama() -> None:
    client = _build_vision_client(
        _worker_config(),
        SimpleNamespace(
            provider="vllm",
            ingestion_provider="vllm",
            vision_provider="ollama",
            base_url="http://vllm-text:8000/v1",
            vision_base_url="http://ollama:11434",
            chat_model="Qwen/Qwen3-14B-AWQ",
            ingestion_model="Qwen/Qwen3-14B-AWQ",
            vision_model="qwen2.5vl:3b",
        ),
    )

    assert client.provider == OLLAMA_PROVIDER
    assert client.base_url == "http://ollama:11434"
    assert client.model == "qwen2.5vl:3b"


def test_ollama_vision_client_uses_api_chat_images_payload(monkeypatch) -> None:
    calls = []

    def fake_request_json(base_url, path, **kwargs):
        calls.append((base_url, path, kwargs))
        return {
            "message": {
                "content": '{"extracted_text":"visible text","caption":"caption","confidence":0.75}'
            }
        }

    monkeypatch.setattr(vision_module, "request_json", fake_request_json)
    result = VisionClient(
        provider="ollama",
        base_url="http://ollama:11434",
        model="llava:latest",
        timeout_seconds=10,
        num_ctx=8192,
    ).analyze_image(content=b"image-bytes", content_type="image/png")

    assert result.extracted_text == "visible text"
    assert result.caption == "caption"
    assert calls[0][0] == "http://ollama:11434"
    assert calls[0][1] == "/api/chat"
    payload = calls[0][2]["payload"]
    assert payload["model"] == "llava:latest"
    assert payload["stream"] is False
    assert payload["think"] is False
    assert payload["options"]["num_ctx"] == 8192
    assert payload["messages"][1]["images"] == ["aW1hZ2UtYnl0ZXM="]
    assert "detailed visual descriptions" in payload["messages"][0]["content"]
    assert "RAG indexing" in payload["messages"][1]["content"]
    assert "not for a generic caption" in payload["messages"][1]["content"]
    assert "main subject" in payload["messages"][1]["content"]
    assert "For vehicles, be especially specific" in payload["messages"][1]["content"]
    assert "make, model" in payload["messages"][1]["content"]
    assert "visible cues" in payload["messages"][1]["content"]
    assert "concise caption" not in payload["messages"][1]["content"]


def test_openai_compatible_vision_client_uses_rag_description_prompt(monkeypatch) -> None:
    calls = []

    def fake_request_json(base_url, path, **kwargs):
        calls.append((base_url, path, kwargs))
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"extracted_text":"visible text","caption":"detailed description","confidence":0.8}'
                    }
                }
            ]
        }

    monkeypatch.setattr(vision_module, "request_json", fake_request_json)
    result = VisionClient(
        provider="openai_compatible",
        base_url="http://vllm-vision:8000",
        model="vision-model",
        timeout_seconds=10,
    ).analyze_image(content=b"image-bytes", content_type="image/png")

    assert result.caption == "detailed description"
    assert calls[0][0] == "http://vllm-vision:8000/v1"
    assert calls[0][1] == "/chat/completions"
    payload = calls[0][2]["payload"]
    assert payload["messages"][0]["role"] == "system"
    assert "detailed visual descriptions" in payload["messages"][0]["content"]
    text_part = payload["messages"][1]["content"][0]
    assert text_part["type"] == "text"
    assert "RAG indexing" in text_part["text"]
    assert "not for a generic caption" in text_part["text"]
    assert "main subject" in text_part["text"]
    assert "For vehicles, be especially specific" in text_part["text"]
    assert "make, model" in text_part["text"]
    assert "visible cues" in text_part["text"]
    assert "concise caption" not in text_part["text"]


def test_openai_compatible_vision_client_supports_structured_layout_repair(monkeypatch) -> None:
    calls = []

    def fake_request_json(base_url, path, **kwargs):
        calls.append((base_url, path, kwargs))
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"blocks":[{"type":"heading","text":"Case Summary"},{"type":"text","text":"Ordered page text"}],"confidence":0.86}'
                    }
                }
            ]
        }

    monkeypatch.setattr(vision_module, "request_json", fake_request_json)
    result = VisionClient(
        provider="openai_compatible",
        base_url="http://vllm-vision:8000",
        model="vision-model",
        timeout_seconds=10,
    ).analyze_layout(content=b"image-bytes", content_type="image/png")

    assert [block.text for block in result.blocks] == ["Case Summary", "Ordered page text"]
    assert result.blocks[0].block_type == "heading"
    assert result.confidence == 0.86
    assert calls[0][0] == "http://vllm-vision:8000/v1"
    assert calls[0][1] == "/chat/completions"
    payload = calls[0][2]["payload"]
    assert payload["messages"][1]["content"][0]["type"] == "text"
    assert "reconstruct the page in correct human reading order" in payload["messages"][1]["content"][0]["text"]
    assert "blocks" in payload["messages"][1]["content"][0]["text"]


def test_ollama_vision_client_supports_structured_layout_repair(monkeypatch) -> None:
    calls = []

    def fake_request_json(base_url, path, **kwargs):
        calls.append((base_url, path, kwargs))
        return {
            "message": {
                "content": '{"blocks":[{"type":"form_field","text":"Case No: 123"}],"confidence":0.81}'
            }
        }

    monkeypatch.setattr(vision_module, "request_json", fake_request_json)
    result = VisionClient(
        provider="ollama",
        base_url="http://ollama:11434",
        model="qwen2.5vl:3b",
        timeout_seconds=10,
        num_ctx=8192,
    ).analyze_layout(content=b"image-bytes", content_type="image/png")

    assert [block.text for block in result.blocks] == ["Case No: 123"]
    assert result.blocks[0].block_type == "form_field"
    assert calls[0][0] == "http://ollama:11434"
    assert calls[0][1] == "/api/chat"
    payload = calls[0][2]["payload"]
    assert payload["format"]["required"] == ["blocks", "confidence"]
    assert payload["messages"][1]["images"] == ["aW1hZ2UtYnl0ZXM="]
    assert "reading order" in payload["messages"][1]["content"]


def test_image_item_text_indexes_visual_description_not_caption() -> None:
    text = _image_item_text("Serial No. 123", "A detailed description of the photographed form.")

    assert "Visible image text:\nSerial No. 123" in text
    assert "Image description:\nA detailed description of the photographed form." in text
    assert "Image caption:" not in text


def _worker_config(*, ollama_vision_model: str = "") -> WorkerConfig:
    return WorkerConfig(
        redis_url="redis://redis:6379/0",
        ingest_queue_name="ingest:jobs",
        graphrag_queue_name="graphrag:jobs",
        graphrag_enabled=False,
        graphrag_community_collection="graphrag_community_summaries",
        graphrag_extraction_concurrency=2,
        graphrag_summary_concurrency=2,
        graphrag_summarize_after_document=False,
        graphrag_partition_rebuild_delay_seconds=60,
        graphrag_max_chunks_per_doc=0,
        graphrag_min_chunk_chars=80,
        graphrag_extraction_checkpoint_ttl_seconds=86400,
        neo4j_uri="bolt://neo4j:7687",
        neo4j_user="neo4j",
        neo4j_password="password",
        neo4j_database="neo4j",
        http_timeout_seconds=45,
        heartbeat_interval_seconds=30,
        ingest_stale_after_seconds=120,
        ollama_retry_base_seconds=2,
        ollama_num_ctx=16384,
        embedding_batch_size=16,
        worker_boot_concurrency=1,
        weak_page_threshold=5,
        full_doc_weak_page_ratio=0.25,
        layered_docling_max_pages=40,
        layered_docling_batch_pages=4,
        pdf_image_analysis_max_images=-1,
        pdf_image_analysis_max_full_page_fallbacks=-1,
        pdf_image_review_threshold=64,
        scanned_visual_region_enabled=True,
        scanned_visual_min_area_ratio=0.03,
        scanned_visual_max_regions_per_page=4,
        scanned_visual_text_mask_padding_px=8,
        ocr_review_confidence_threshold=0.9,
        native_text_min_chars_per_page=10,
        chunk_target_tokens=512,
        chunk_overlap_tokens=64,
        parent_max_tokens=2048,
        metadata_use_gliner=False,
        topic_taxonomy=("contracts",),
        mock=MockSwitches(global_enabled=False, llm=False, embeddings=False, ocr=False),
        model_provider=ModelProviderConfig(
            provider="vllm",
            ollama_base_url="http://ollama:11434",
            ollama_chat_model="llama3.1:8b",
            ollama_embed_model="nomic-embed-text:latest",
            ollama_chat_timeout_seconds=180,
            ollama_embed_timeout_seconds=45,
            dense_cache_dir="/models/fastembed",
            sparse_model="Qdrant/bm25",
            sparse_cache_dir="/models/fastembed",
        ),
        backend=BackendConfig(internal_url="http://api:8000", service_token="token"),
        minio=MinioConfig(
            endpoint="minio:9000",
            access_key="agenticrag",
            secret_key="secret",
            bucket="agenticrag-uploads",
            secure=False,
        ),
        qdrant=QdrantConfig(url="http://qdrant:6333", collection="documents", upsert_batch_size=64),
        vision=VisionConfig(
            base_url="http://vllm-vision:8000/v1",
            model="Qwen/Qwen2.5-VL-7B-Instruct-AWQ",
            ollama_model=ollama_vision_model,
            ollama_num_ctx=8192,
        ),
    )
