import os  # unused on purpose -> ruff F401 makes the "lint" check fail


def test_ci_gate_blocks_failing_tests():
    assert 1 + 1 == 3  # wrong on purpose -> makes the "test" check fail