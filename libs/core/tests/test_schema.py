"""
Tests for YAML schema models, particularly ActionDef.
"""

import pytest
from pydantic import ValidationError

from phalanx_core.yaml.schema import (
    ActionDef,
    OutputDef,
    SoulDef,
    BlockDef,
    TransitionDef,
    WorkflowDef,
    PhalanxWorkflowFile,
)


class TestOutputDef:
    """Tests for OutputDef schema model."""

    def test_outputdef_default_type(self):
        """OutputDef has default type of 'artifact_only'."""
        output = OutputDef()
        assert output.type == "artifact_only"
        assert output.config == {}

    def test_outputdef_custom_type(self):
        """OutputDef can be created with custom type."""
        output = OutputDef(type="workspace")
        assert output.type == "workspace"
        assert output.config == {}

    def test_outputdef_with_config(self):
        """OutputDef can have custom config."""
        output = OutputDef(type="workspace", config={"key": "value"})
        assert output.type == "workspace"
        assert output.config == {"key": "value"}

    def test_outputdef_invalid_type(self):
        """OutputDef only allows artifact_only or workspace types."""
        with pytest.raises(ValidationError):
            OutputDef(type="invalid_type")  # type: ignore


class TestActionDef:
    """Tests for ActionDef schema model."""

    def test_actiondef_required_fields(self):
        """ActionDef requires id and instruction fields."""
        with pytest.raises(ValidationError):
            ActionDef(id="test1")  # type: ignore  # missing instruction

        with pytest.raises(ValidationError):
            ActionDef(instruction="Do something")  # type: ignore  # missing id

    def test_actiondef_valid_minimal(self):
        """ActionDef with only required fields (id and instruction) is valid."""
        action = ActionDef(id="task1", instruction="Do something")
        assert action.id == "task1"
        assert action.instruction == "Do something"
        assert action.context is None
        assert action.output.type == "artifact_only"
        assert action.output.config == {}

    def test_actiondef_valid_with_context(self):
        """ActionDef with all fields is valid."""
        action = ActionDef(
            id="task2",
            instruction="Review the code",
            context="Here is the code to review",
        )
        assert action.id == "task2"
        assert action.instruction == "Review the code"
        assert action.context == "Here is the code to review"
        assert action.output.type == "artifact_only"

    def test_actiondef_context_optional(self):
        """ActionDef context field is optional."""
        action1 = ActionDef(id="task3", instruction="Do something", context=None)
        assert action1.context is None

        action2 = ActionDef(id="task4", instruction="Do something")
        assert action2.context is None

    def test_actiondef_fields_are_strings(self):
        """ActionDef id and instruction must be strings."""
        with pytest.raises(ValidationError):
            ActionDef(id=123, instruction="Do something")  # type: ignore

        with pytest.raises(ValidationError):
            ActionDef(id="task5", instruction=456)  # type: ignore

    def test_actiondef_context_must_be_string_or_none(self):
        """ActionDef context must be string or None."""
        with pytest.raises(ValidationError):
            ActionDef(id="task6", instruction="Do something", context=123)  # type: ignore

        action = ActionDef(id="task6", instruction="Do something", context="")
        assert action.context == ""

    def test_actiondef_string_fields_empty_allowed(self):
        """ActionDef allows empty strings (though semantically odd)."""
        action = ActionDef(id="", instruction="")
        assert action.id == ""
        assert action.instruction == ""

    def test_actiondef_from_dict(self):
        """ActionDef can be instantiated from dict."""
        data = {
            "id": "task7",
            "instruction": "Analyze this",
            "context": "Some context",
        }
        action = ActionDef(**data)
        assert action.id == "task7"
        assert action.instruction == "Analyze this"
        assert action.context == "Some context"

    def test_actiondef_model_dump(self):
        """ActionDef can be serialized to dict."""
        action = ActionDef(
            id="task8",
            instruction="Review",
            context="Context here",
        )
        dumped = action.model_dump()
        assert dumped["id"] == "task8"
        assert dumped["instruction"] == "Review"
        assert dumped["context"] == "Context here"
        assert dumped["output"]["type"] == "artifact_only"

    def test_actiondef_model_dump_excludes_none(self):
        """ActionDef.model_dump(exclude_none=True) excludes None context."""
        action = ActionDef(id="task9", instruction="Do it")
        dumped = action.model_dump(exclude_none=True)
        assert "id" in dumped
        assert "instruction" in dumped
        assert "context" not in dumped

    def test_actiondef_with_custom_output(self):
        """ActionDef can be created with custom output."""
        action = ActionDef(
            id="task10",
            instruction="Do it",
            output={"type": "workspace", "config": {"key": "value"}},
        )
        assert action.output.type == "workspace"
        assert action.output.config == {"key": "value"}

    def test_actiondef_output_type_default(self):
        """ActionDef().output.type defaults to 'artifact_only'."""
        action = ActionDef(id="a", instruction="do it")
        assert action.output.type == "artifact_only"

    def test_actiondef_output_type_workspace(self):
        """ActionDef with workspace output type."""
        action = ActionDef(
            id="a",
            instruction="do it",
            output={"type": "workspace", "config": {}},
        )
        assert action.output.type == "workspace"


class TestSchemaModelsUnaffected:
    """Verify that existing schema models still work after ActionDef addition."""

    def test_souldef_unchanged(self):
        """SoulDef should work as before."""
        soul = SoulDef(
            id="soul1",
            role="Researcher",
            system_prompt="You are a researcher",
        )
        assert soul.id == "soul1"
        assert soul.role == "Researcher"

    def test_blockdef_unchanged(self):
        """BlockDef should work as before."""
        block = BlockDef(type="linear", soul_ref="soul1")
        assert block.type == "linear"
        assert block.soul_ref == "soul1"

    def test_transitiondef_unchanged(self):
        """TransitionDef should work as before."""
        transition = TransitionDef(**{"from": "block1", "to": "block2"})
        assert transition.from_ == "block1"
        assert transition.to == "block2"

    def test_workflowdef_unchanged(self):
        """WorkflowDef should work as before."""
        workflow = WorkflowDef(name="test", entry="block1")
        assert workflow.name == "test"
        assert workflow.entry == "block1"

    def test_phalanxworkflowfile_unchanged(self):
        """PhalanxWorkflowFile should work as before."""
        workflow_def = WorkflowDef(name="test", entry="block1")
        pwf = PhalanxWorkflowFile(workflow=workflow_def)
        assert pwf.workflow.name == "test"
        assert pwf.version == "1.0"
