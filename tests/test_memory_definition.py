"""'What is a cat?' asks what a cat is: never answered from a saved note."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import memory  # noqa: E402


def test_definition_questions_skip_notes():
    for q in ("what is a cat", "what is a raspberry pi", "whats an otter", "what are dogs"):
        assert memory.DEFINITION.match(q), q
    for q in ("where are my keys", "what is my wifi password", "whats the garage code",
              "who is sam", "what are my plans"):
        assert not memory.DEFINITION.match(q), q
