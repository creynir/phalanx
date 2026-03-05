from typing import Any, AsyncGenerator, Dict
from pydantic import BaseModel

from phalanx_core.primitives import Soul, Action
from phalanx_core.llm.client import LiteLLMClient


class ExecutionResult(BaseModel):
    """
    The result of a single action execution by an agent.
    """

    task_id: str
    soul_id: str
    output: str
    metadata: Dict[str, Any] = {}
    cost_usd: float = 0.0
    total_tokens: int = 0


class PhalanxTeamRunner:
    """
    Core executor that runs an Action using a specific Soul via the LLM client.
    """

    def __init__(self, model_name: str = "gpt-4o"):
        self.llm_client = LiteLLMClient(model_name=model_name)

    async def execute_task(self, task: Action, soul: Soul) -> ExecutionResult:
        """
        Executes an action synchronously (waits for full completion).
        """
        messages = [{"role": "user", "content": self._build_prompt(task)}]

        response = await self.llm_client.achat(messages=messages, system_prompt=soul.system_prompt)

        return ExecutionResult(
            task_id=task.id,
            soul_id=soul.id,
            output=response["content"],
            cost_usd=response["cost_usd"],
            total_tokens=response["total_tokens"],
        )

    async def stream_task(self, task: Action, soul: Soul) -> AsyncGenerator[str, None]:
        """
        Executes an action and streams the response tokens back.
        """
        messages = [{"role": "user", "content": self._build_prompt(task)}]

        async for chunk in self.llm_client.astream_chat(
            messages=messages, system_prompt=soul.system_prompt
        ):
            yield chunk

    def _build_prompt(self, task: Action) -> str:
        """
        Constructs the final prompt string from the action definition.
        """
        prompt = task.instruction
        if task.context:
            prompt += f"\n\nContext:\n{task.context}"
        return prompt
