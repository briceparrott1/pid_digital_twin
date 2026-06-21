# Unit test for build_leaf_prompt: guards against the prompt failing to build
# at all (e.g. a reference to an undefined name), since no other test exercises
# the real prompt string -- every leaf_read test mocks around it.
from __future__ import annotations

from engine.leaf.prompt import build_leaf_prompt


def test_build_leaf_prompt_returns_nonempty_string_with_schema_and_examples():
    prompt = build_leaf_prompt()
    assert isinstance(prompt, str)
    assert "split_nodes" in prompt
    assert "connects_to" in prompt
    assert "Example 6" in prompt
    assert "Tag formats" in prompt
    assert "Example 7" in prompt
