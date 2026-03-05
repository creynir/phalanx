import pytest
from pydantic import ValidationError
from phalanx_core.primitives import Soul, Action


def test_soul_validation():
    soul = Soul(id="test1", role="Coder", system_prompt="Write code.")
    assert soul.id == "test1"
    assert soul.role == "Coder"
    assert soul.system_prompt == "Write code."
    assert soul.tools is None

    with pytest.raises(ValidationError):
        Soul(role="Coder", system_prompt="Missing id")


def test_action_validation():
    action = Action(id="task1", instruction="Do work")
    assert action.id == "task1"
    assert action.instruction == "Do work"
    assert action.context is None

    action_with_context = Action(id="task2", instruction="Do work", context="Context here")
    assert action_with_context.context == "Context here"
