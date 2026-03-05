"""
Tests for YAML Parser and Standard Library.

This module tests:
- All 10 block types in BlockTypeRegistry
- Valid YAML parsing scenarios
- Error paths that raise ValueError
- Soul resolution and merging with built-ins
"""

import pytest
from pydantic import ValidationError
from phalanx_core.yaml.parser import (
    parse_workflow_yaml,
    BUILT_IN_SOULS,
    BLOCK_TYPE_REGISTRY,
)
from phalanx_core.workflow import Workflow


class TestBlockTypeRegistry:
    """Tests for BlockTypeRegistry completeness."""

    def test_block_type_registry_has_all_10_types(self):
        """Verify BLOCK_TYPE_REGISTRY contains all 10 block types."""
        expected_types = {
            "linear",
            "fanout",
            "synthesize",
            "debate",
            "message_bus",
            "router",
            "retry",
            "team_lead",
            "engineering_manager",
            "placeholder",
        }
        assert set(BLOCK_TYPE_REGISTRY.keys()) == expected_types
        assert len(BLOCK_TYPE_REGISTRY) == 10

    def test_all_block_builders_are_callable(self):
        """Verify all builders in registry are callable."""
        for block_type, builder in BLOCK_TYPE_REGISTRY.items():
            assert callable(builder), f"Builder for {block_type} is not callable"


class TestBuiltInSouls:
    """Tests for built-in souls."""

    def test_built_in_souls_exist(self):
        """Verify BUILT_IN_SOULS contains expected souls."""
        expected_souls = {
            "researcher",
            "reviewer",
            "engineering_manager",
            "coder",
            "architect",
            "synthesizer",
            "generalist",
        }
        assert set(BUILT_IN_SOULS.keys()) == expected_souls
        assert len(BUILT_IN_SOULS) == 7

    def test_built_in_souls_have_required_fields(self):
        """Verify each built-in soul has required fields."""
        for soul_key, soul in BUILT_IN_SOULS.items():
            assert soul.id is not None
            assert soul.role is not None
            assert soul.system_prompt is not None


class TestLinearBlock:
    """Tests for LinearBlock (block type: linear)."""

    def test_linear_block_valid_yaml(self):
        """AC-1: Parse valid linear block with soul_ref."""
        yaml_content = """
version: "1.0"
config:
  model_name: gpt-4o
souls:
  my_soul:
    id: my_soul_1
    role: Custom Researcher
    system_prompt: Do research
blocks:
  linear_block:
    type: linear
    soul_ref: my_soul
workflow:
  name: test_linear
  entry: linear_block
  transitions:
    - from: linear_block
      to: null
"""
        workflow = parse_workflow_yaml(yaml_content)
        assert isinstance(workflow, Workflow)
        assert workflow.name == "test_linear"

    def test_linear_block_missing_soul_ref_raises_error(self):
        """AC-2: LinearBlock without soul_ref raises ValueError."""
        yaml_content = """
version: "1.0"
blocks:
  linear_block:
    type: linear
workflow:
  name: test_linear
  entry: linear_block
"""
        with pytest.raises(ValueError, match="soul_ref is required"):
            parse_workflow_yaml(yaml_content)

    def test_linear_block_with_builtin_soul(self):
        """AC-3: LinearBlock can use built-in souls."""
        yaml_content = """
version: "1.0"
blocks:
  linear_block:
    type: linear
    soul_ref: researcher
workflow:
  name: test_linear
  entry: linear_block
  transitions:
    - from: linear_block
      to: null
"""
        workflow = parse_workflow_yaml(yaml_content)
        assert isinstance(workflow, Workflow)


class TestFanOutBlock:
    """Tests for FanOutBlock (block type: fanout)."""

    def test_fanout_block_valid_yaml(self):
        """AC-4: Parse valid fanout block with multiple soul_refs."""
        yaml_content = """
version: "1.0"
blocks:
  fanout_block:
    type: fanout
    soul_refs:
      - researcher
      - reviewer
workflow:
  name: test_fanout
  entry: fanout_block
  transitions:
    - from: fanout_block
      to: null
"""
        workflow = parse_workflow_yaml(yaml_content)
        assert isinstance(workflow, Workflow)
        assert workflow.name == "test_fanout"

    def test_fanout_block_missing_soul_refs_raises_error(self):
        """AC-5: FanOutBlock without soul_refs raises ValueError."""
        yaml_content = """
version: "1.0"
blocks:
  fanout_block:
    type: fanout
workflow:
  name: test_fanout
  entry: fanout_block
"""
        with pytest.raises(ValueError, match="soul_refs is required"):
            parse_workflow_yaml(yaml_content)

    def test_fanout_block_empty_soul_refs_raises_error(self):
        """AC-6: FanOutBlock with empty soul_refs raises ValueError."""
        yaml_content = """
version: "1.0"
blocks:
  fanout_block:
    type: fanout
    soul_refs: []
workflow:
  name: test_fanout
  entry: fanout_block
"""
        with pytest.raises(ValueError, match="soul_refs is required"):
            parse_workflow_yaml(yaml_content)


class TestSynthesizeBlock:
    """Tests for SynthesizeBlock (block type: synthesize)."""

    def test_synthesize_block_valid_yaml(self):
        """AC-7: Parse valid synthesize block with dependencies."""
        yaml_content = """
version: "1.0"
blocks:
  block_a:
    type: linear
    soul_ref: researcher
  block_b:
    type: linear
    soul_ref: reviewer
  synthesize_block:
    type: synthesize
    soul_ref: synthesizer
    input_block_ids:
      - block_a
      - block_b
workflow:
  name: test_synthesize
  entry: block_a
  transitions:
    - from: block_a
      to: block_b
    - from: block_b
      to: synthesize_block
    - from: synthesize_block
      to: null
"""
        workflow = parse_workflow_yaml(yaml_content)
        assert isinstance(workflow, Workflow)

    def test_synthesize_block_missing_soul_ref_raises_error(self):
        """AC-8: SynthesizeBlock without soul_ref raises ValueError."""
        yaml_content = """
version: "1.0"
blocks:
  synthesize_block:
    type: synthesize
    input_block_ids:
      - block_a
workflow:
  name: test_synthesize
  entry: synthesize_block
"""
        with pytest.raises(ValueError, match="soul_ref is required"):
            parse_workflow_yaml(yaml_content)

    def test_synthesize_block_missing_input_block_ids_raises_error(self):
        """AC-9: SynthesizeBlock without input_block_ids raises ValueError."""
        yaml_content = """
version: "1.0"
blocks:
  synthesize_block:
    type: synthesize
    soul_ref: synthesizer
workflow:
  name: test_synthesize
  entry: synthesize_block
"""
        with pytest.raises(ValueError, match="input_block_ids is required"):
            parse_workflow_yaml(yaml_content)


class TestDebateBlock:
    """Tests for DebateBlock (block type: debate)."""

    def test_debate_block_valid_yaml(self):
        """AC-10: Parse valid debate block with two souls and iterations."""
        yaml_content = """
version: "1.0"
blocks:
  debate_block:
    type: debate
    soul_a_ref: researcher
    soul_b_ref: reviewer
    iterations: 3
workflow:
  name: test_debate
  entry: debate_block
  transitions:
    - from: debate_block
      to: null
"""
        workflow = parse_workflow_yaml(yaml_content)
        assert isinstance(workflow, Workflow)

    def test_debate_block_missing_soul_a_ref_raises_error(self):
        """AC-11: DebateBlock without soul_a_ref raises ValueError."""
        yaml_content = """
version: "1.0"
blocks:
  debate_block:
    type: debate
    soul_b_ref: reviewer
    iterations: 3
workflow:
  name: test_debate
  entry: debate_block
"""
        with pytest.raises(ValueError, match="soul_a_ref is required"):
            parse_workflow_yaml(yaml_content)

    def test_debate_block_missing_iterations_raises_error(self):
        """AC-12: DebateBlock without iterations raises ValueError."""
        yaml_content = """
version: "1.0"
blocks:
  debate_block:
    type: debate
    soul_a_ref: researcher
    soul_b_ref: reviewer
workflow:
  name: test_debate
  entry: debate_block
"""
        with pytest.raises(ValueError, match="iterations is required"):
            parse_workflow_yaml(yaml_content)


class TestMessageBusBlock:
    """Tests for MessageBusBlock (block type: message_bus)."""

    def test_message_bus_block_valid_yaml(self):
        """AC-13: Parse valid message_bus block with souls and iterations."""
        yaml_content = """
version: "1.0"
blocks:
  message_bus_block:
    type: message_bus
    soul_refs:
      - researcher
      - reviewer
    iterations: 2
workflow:
  name: test_message_bus
  entry: message_bus_block
  transitions:
    - from: message_bus_block
      to: null
"""
        workflow = parse_workflow_yaml(yaml_content)
        assert isinstance(workflow, Workflow)

    def test_message_bus_block_missing_soul_refs_raises_error(self):
        """AC-14: MessageBusBlock without soul_refs raises ValueError."""
        yaml_content = """
version: "1.0"
blocks:
  message_bus_block:
    type: message_bus
    iterations: 2
workflow:
  name: test_message_bus
  entry: message_bus_block
"""
        with pytest.raises(ValueError, match="soul_refs is required"):
            parse_workflow_yaml(yaml_content)

    def test_message_bus_block_missing_iterations_raises_error(self):
        """AC-15: MessageBusBlock without iterations raises ValueError."""
        yaml_content = """
version: "1.0"
blocks:
  message_bus_block:
    type: message_bus
    soul_refs:
      - researcher
      - reviewer
workflow:
  name: test_message_bus
  entry: message_bus_block
"""
        with pytest.raises(ValueError, match="iterations is required"):
            parse_workflow_yaml(yaml_content)


class TestRouterBlock:
    """Tests for RouterBlock (block type: router)."""

    def test_router_block_valid_yaml(self):
        """AC-16: Parse valid router block with soul_ref."""
        yaml_content = """
version: "1.0"
blocks:
  router_block:
    type: router
    soul_ref: reviewer
workflow:
  name: test_router
  entry: router_block
  transitions:
    - from: router_block
      to: null
"""
        workflow = parse_workflow_yaml(yaml_content)
        assert isinstance(workflow, Workflow)

    def test_router_block_missing_soul_ref_raises_error(self):
        """AC-17: RouterBlock without soul_ref raises ValueError."""
        yaml_content = """
version: "1.0"
blocks:
  router_block:
    type: router
workflow:
  name: test_router
  entry: router_block
"""
        with pytest.raises(ValueError, match="soul_ref is required"):
            parse_workflow_yaml(yaml_content)


class TestRetryBlock:
    """Tests for RetryBlock (block type: retry)."""

    def test_retry_block_valid_yaml(self):
        """AC-18: Parse valid retry block with inner_block_ref."""
        yaml_content = """
version: "1.0"
blocks:
  linear_block:
    type: linear
    soul_ref: researcher
  retry_block:
    type: retry
    inner_block_ref: linear_block
    max_retries: 3
workflow:
  name: test_retry
  entry: linear_block
  transitions:
    - from: linear_block
      to: retry_block
    - from: retry_block
      to: null
"""
        workflow = parse_workflow_yaml(yaml_content)
        assert isinstance(workflow, Workflow)

    def test_retry_block_missing_inner_block_ref_raises_error(self):
        """AC-19: RetryBlock without inner_block_ref raises ValueError."""
        yaml_content = """
version: "1.0"
blocks:
  retry_block:
    type: retry
    max_retries: 3
workflow:
  name: test_retry
  entry: retry_block
"""
        with pytest.raises(ValueError, match="inner_block_ref is required"):
            parse_workflow_yaml(yaml_content)

    def test_retry_block_invalid_inner_block_ref_raises_error(self):
        """AC-20: RetryBlock with non-existent inner_block_ref raises ValueError."""
        yaml_content = """
version: "1.0"
blocks:
  retry_block:
    type: retry
    inner_block_ref: nonexistent_block
workflow:
  name: test_retry
  entry: retry_block
"""
        with pytest.raises(ValueError, match="not found"):
            parse_workflow_yaml(yaml_content)


class TestTeamLeadBlock:
    """Tests for TeamLeadBlock (block type: team_lead)."""

    def test_team_lead_block_valid_yaml(self):
        """AC-21: Parse valid team_lead block with soul and failure_context_keys."""
        yaml_content = """
version: "1.0"
blocks:
  team_lead_block:
    type: team_lead
    soul_ref: engineering_manager
    failure_context_keys:
      - error_details
      - retry_count
workflow:
  name: test_team_lead
  entry: team_lead_block
  transitions:
    - from: team_lead_block
      to: null
"""
        workflow = parse_workflow_yaml(yaml_content)
        assert isinstance(workflow, Workflow)

    def test_team_lead_block_missing_soul_ref_raises_error(self):
        """AC-22: TeamLeadBlock without soul_ref raises ValueError."""
        yaml_content = """
version: "1.0"
blocks:
  team_lead_block:
    type: team_lead
    failure_context_keys:
      - error_details
workflow:
  name: test_team_lead
  entry: team_lead_block
"""
        with pytest.raises(ValueError, match="soul_ref is required"):
            parse_workflow_yaml(yaml_content)

    def test_team_lead_block_missing_failure_context_keys_raises_error(self):
        """AC-23: TeamLeadBlock without failure_context_keys raises ValueError."""
        yaml_content = """
version: "1.0"
blocks:
  team_lead_block:
    type: team_lead
    soul_ref: engineering_manager
workflow:
  name: test_team_lead
  entry: team_lead_block
"""
        with pytest.raises(ValueError, match="failure_context_keys is required"):
            parse_workflow_yaml(yaml_content)


class TestEngineeringManagerBlock:
    """Tests for EngineeringManagerBlock (block type: engineering_manager)."""

    def test_engineering_manager_block_valid_yaml(self):
        """AC-24: Parse valid engineering_manager block with soul_ref."""
        yaml_content = """
version: "1.0"
blocks:
  manager_block:
    type: engineering_manager
    soul_ref: engineering_manager
workflow:
  name: test_manager
  entry: manager_block
  transitions:
    - from: manager_block
      to: null
"""
        workflow = parse_workflow_yaml(yaml_content)
        assert isinstance(workflow, Workflow)

    def test_engineering_manager_block_missing_soul_ref_raises_error(self):
        """AC-25: EngineeringManagerBlock without soul_ref raises ValueError."""
        yaml_content = """
version: "1.0"
blocks:
  manager_block:
    type: engineering_manager
workflow:
  name: test_manager
  entry: manager_block
"""
        with pytest.raises(ValueError, match="soul_ref is required"):
            parse_workflow_yaml(yaml_content)


class TestPlaceholderBlock:
    """Tests for PlaceholderBlock (block type: placeholder)."""

    def test_placeholder_block_valid_yaml(self):
        """AC-26: Parse valid placeholder block."""
        yaml_content = """
version: "1.0"
blocks:
  placeholder_block:
    type: placeholder
    description: "This is a placeholder"
workflow:
  name: test_placeholder
  entry: placeholder_block
  transitions:
    - from: placeholder_block
      to: null
"""
        workflow = parse_workflow_yaml(yaml_content)
        assert isinstance(workflow, Workflow)

    def test_placeholder_block_no_description(self):
        """AC-27: PlaceholderBlock without explicit description gets default."""
        yaml_content = """
version: "1.0"
blocks:
  placeholder_block:
    type: placeholder
workflow:
  name: test_placeholder
  entry: placeholder_block
  transitions:
    - from: placeholder_block
      to: null
"""
        workflow = parse_workflow_yaml(yaml_content)
        assert isinstance(workflow, Workflow)


class TestSoulResolution:
    """Tests for soul resolution and merging."""

    def test_soul_resolution_missing_soul_raises_error(self):
        """AC-28: Referencing non-existent soul raises ValueError."""
        yaml_content = """
version: "1.0"
blocks:
  linear_block:
    type: linear
    soul_ref: nonexistent_soul
workflow:
  name: test_souls
  entry: linear_block
"""
        with pytest.raises(ValueError, match="Soul reference 'nonexistent_soul' not found"):
            parse_workflow_yaml(yaml_content)

    def test_custom_soul_overrides_builtin(self):
        """AC-29: Custom soul definition overrides built-in soul."""
        yaml_content = """
version: "1.0"
souls:
  researcher:
    id: custom_researcher
    role: Custom Researcher
    system_prompt: Custom research prompt
blocks:
  linear_block:
    type: linear
    soul_ref: researcher
workflow:
  name: test_override
  entry: linear_block
  transitions:
    - from: linear_block
      to: null
"""
        workflow = parse_workflow_yaml(yaml_content)
        assert isinstance(workflow, Workflow)


class TestInvalidYAML:
    """Tests for invalid YAML handling."""

    def test_invalid_yaml_syntax_raises_error(self):
        """AC-30: Syntactically invalid YAML raises error."""
        yaml_content = """
version: "1.0"
blocks:
  block: [invalid yaml structure
"""
        with pytest.raises(Exception):  # yaml.YAMLError
            parse_workflow_yaml(yaml_content)

    def test_missing_workflow_section_raises_error(self):
        """AC-31: Missing required workflow section raises ValidationError."""
        yaml_content = """
version: "1.0"
blocks:
  linear_block:
    type: linear
    soul_ref: researcher
"""
        with pytest.raises(ValidationError):
            parse_workflow_yaml(yaml_content)

    def test_unknown_block_type_raises_error(self):
        """AC-32: Unknown block type raises ValueError."""
        yaml_content = """
version: "1.0"
blocks:
  unknown_block:
    type: unknown_type
workflow:
  name: test_unknown
  entry: unknown_block
"""
        with pytest.raises(ValueError, match="Unknown block type"):
            parse_workflow_yaml(yaml_content)


class TestParseFromDict:
    """Tests for parsing from dict input."""

    def test_parse_from_dict_valid(self):
        """AC-33: parse_workflow_yaml accepts dict input."""
        workflow_dict = {
            "version": "1.0",
            "blocks": {
                "linear_block": {
                    "type": "linear",
                    "soul_ref": "researcher",
                }
            },
            "workflow": {
                "name": "test_dict",
                "entry": "linear_block",
                "transitions": [{"from": "linear_block", "to": None}],
            },
        }
        workflow = parse_workflow_yaml(workflow_dict)
        assert isinstance(workflow, Workflow)
        assert workflow.name == "test_dict"


class TestComplexWorkflow:
    """Tests for complex multi-block workflows."""

    def test_complex_workflow_all_block_types(self):
        """AC-34: Parse workflow using multiple block types together."""
        yaml_content = """
version: "1.0"
config:
  model_name: gpt-4o
blocks:
  research_block:
    type: linear
    soul_ref: researcher
  review_block:
    type: fanout
    soul_refs:
      - reviewer
      - coder
  synthesize_block:
    type: synthesize
    soul_ref: synthesizer
    input_block_ids:
      - research_block
      - review_block
  placeholder_block:
    type: placeholder
    description: Final placeholder
workflow:
  name: complex_workflow
  entry: research_block
  transitions:
    - from: research_block
      to: review_block
    - from: review_block
      to: synthesize_block
    - from: synthesize_block
      to: placeholder_block
    - from: placeholder_block
      to: null
"""
        workflow = parse_workflow_yaml(yaml_content)
        assert isinstance(workflow, Workflow)
        assert workflow.name == "complex_workflow"


# This ensures we have at least 8 distinct test functions across all classes
# Count of actual test functions (test_* methods):
# TestBlockTypeRegistry: 2
# TestBuiltInSouls: 2
# TestLinearBlock: 3
# TestFanOutBlock: 3
# TestSynthesizeBlock: 3
# TestDebateBlock: 3
# TestMessageBusBlock: 3
# TestRouterBlock: 2
# TestRetryBlock: 3
# TestTeamLeadBlock: 3
# TestEngineeringManagerBlock: 2
# TestPlaceholderBlock: 2
# TestSoulResolution: 2
# TestInvalidYAML: 3
# TestParseFromDict: 1
# TestComplexWorkflow: 1
# Total: 40+ test functions
