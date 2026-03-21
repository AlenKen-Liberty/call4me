import pytest
import os
import sys

# Ensure the root directory is in the python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from call4me.llm.client import Chat2APIClient
from call4me.config import LLMConfig
import time

def generate_llm_client(model_name: str) -> Chat2APIClient:
    """Helper to generate an LLM client pointing to Chat2API"""
    config = LLMConfig(
        base_url="http://127.0.0.1:7860/v1",
        api_key="call4me",
        model=model_name,
        temperature=0.2,
        max_output_tokens=180,
        stream=False # Disable streaming for simple testing
    )
    return Chat2APIClient(config)

def test_llm_gemini_fast():
    """Test Chat2API with the 'gemini' model."""
    client = generate_llm_client("gemini")
    
    start_time = time.time()
    try:
        response = client.next_action(
            system_prompt="You are a helpful customer service assistant answering the phone.",
            history=[
                {"role": "user", "content": "Hello, I am calling about a charge on my credit card."}
            ]
        )
        duration = time.time() - start_time
        print(f"\\n[Gemini] Response time: {duration:.2f}s")
        print(f"[Gemini] Response text: {response.raw}")
        assert response.raw is not None
        assert len(response.raw) > 0
    except Exception as e:
        pytest.fail(f"Gemini model test failed: {e}")

def test_llm_codex_fast():
    """Test Chat2API with the 'codex' model."""
    client = generate_llm_client("codex")
    
    start_time = time.time()
    try:
        response = client.next_action(
            system_prompt="You are a helpful customer service assistant answering the phone. Keep it brief.",
            history=[
                {"role": "user", "content": "Hello, I want to rebook my flight to Toronto."}
            ]
        )
        duration = time.time() - start_time
        print(f"\\n[Codex] Response time: {duration:.2f}s")
        print(f"[Codex] Response text: {response.raw}")
        assert response.raw is not None
        assert len(response.raw) > 0
    except Exception as e:
        pytest.fail(f"Codex model test failed: {e}")
