import pytest
import os
import sys

# Ensure the root directory is in the python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

def test_imports():
    """Smoke test to ensure all major modules can be imported without errors."""
    import call4me.config
    import call4me.agent
    import call4me.browser.gv_controller
    import call4me.audio.capture
    import call4me.audio.playback
    import call4me.audio.pulse_setup
    
    assert True, "All modules imported successfully"

def test_config_loading():
    """Test that the configuration loads properly (or fails gracefully)."""
    from call4me.config import load_config
    import yaml
    
    # We can test loading from a valid config structure
    yaml_content = """
llm:
  model: "gpt-4"
  api_key: "test_key"
stt:
  model_size: "small"
tts:
  model_path: "en_US-amy-medium.onnx"
"""
    with open("/tmp/test_config.yaml", "w") as f:
        f.write(yaml_content)
        
    config = load_config("/tmp/test_config.yaml")
    assert config.llm.model == "gpt-4"
    assert config.stt.model_size == "small"
    assert config.tts.model_path == "en_US-amy-medium.onnx"
    
    # Clean up
    if os.path.exists("/tmp/test_config.yaml"):
        os.remove("/tmp/test_config.yaml")

def test_audio_pulse_setup_functions():
    """Test importing and verifying function signatures in pulse_setup."""
    from call4me.audio.pulse_setup import PulseAudioManager
    from call4me.config import AudioConfig
    # We won't actually run it to avoid side effects on the system during test,
    # but we ensure it is accessible.
    manager = PulseAudioManager(config=AudioConfig())
    assert hasattr(manager, "ensure_devices")
