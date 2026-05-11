import pytest
from cpplyzer import format_generated_at_tr_eu

def test_format_generated_at_tr_eu_valueerror():
    # Test handling of invalid ISO timestamp
    invalid_timestamp = 'invalid-timestamp-format'
    result = format_generated_at_tr_eu(invalid_timestamp)
    assert result == invalid_timestamp
