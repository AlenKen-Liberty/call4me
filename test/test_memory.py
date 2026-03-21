import pytest
import os
import sys
import tempfile
from pathlib import Path

# Ensure the root directory is in the python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from call4me.memory import CallMemoryService, PostCallExtractor
from call4me.agent import CallResult
from call4me.stt import TranscriptEvent
from call4me.config import LLMConfig
from call4me.llm import Chat2APIClient

@pytest.fixture
def temp_db():
    """Provides a temporary SQLite database for memory testing."""
    fd, path = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    yield path
    os.unlink(path)

def test_memory_service_save_and_retrieve(temp_db):
    memory = CallMemoryService(db_path=temp_db)
    
    # Save a test IVR map
    memory.save_ivr_map(company="TestCorp", phone="12345", path="Press 1 for English")
    
    # Save a test strategy that matches the text of the task query well
    memory.save_strategy(company="TestCorp", strategy="Billing Inquiry: Mention you are a loyal customer.")
    
    # Retrieve context
    context = memory.get_context_for_call("TestCorp", "Billing Inquiry")
    
    assert "Press 1 for English" in context
    assert "Mention you are a loyal customer" in context

def test_post_call_extractor_prompt_generation(temp_db, monkeypatch):
    """Test that the extractor builds the prompt correctly without calling the live LLM."""
    
    config = LLMConfig(base_url="dummy", api_key="dummy", model="dummy")
    dummy_llm = Chat2APIClient(config)
    memory = CallMemoryService(db_path=temp_db)
    
    extractor = PostCallExtractor(dummy_llm, memory, None)
    
    transcripts = [
        TranscriptEvent(0, 5000, 1000, "Thank you for calling."),
        TranscriptEvent(5000, 7000, 800, "Press 1 for support.")
    ]
    
    result = CallResult(
        completed=True,
        summary="Got support",
        company="TestCorp",
        duration_sec=120,
        ivr_steps=["1"],
        transcripts=transcripts
    )
    
    # Mock the LLM call to return a valid JSON response
    def mock_complete(*args, **kwargs):
        return '''{
  "ivr_path": "1 -> wait",
  "ivr_shortcut": "1",
  "avg_hold_minutes": 0,
  "strategies_that_worked": ["Being polite"],
  "strategies_that_failed": [],
  "general_tips": [],
  "company_specific_notes": ""
}'''
    
    monkeypatch.setattr(dummy_llm, "complete_text", mock_complete)
    
    # This should execute without throwing parsing errors
    extractor.extract_and_save(
        "TestCorp", "123456", "Get Support", transcripts, result, ["1"]
    )
    
    # Verify the memory was saved
    context = memory.get_context_for_call("TestCorp", "Get Support")
    assert "1 -> wait" in context
    assert "Being polite" in context
