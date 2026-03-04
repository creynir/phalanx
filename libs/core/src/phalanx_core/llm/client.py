from typing import Any, AsyncGenerator, Dict, List, Optional
from litellm import acompletion
from pydantic import BaseModel


class LLMMessage(BaseModel):
    role: str
    content: str


class LiteLLMClient:
    """
    An async generator LiteLLM adapter matching the OpenAI SDK format.
    Supports streaming and standard completion.
    """

    def __init__(self, model_name: str = "gpt-4o"):
        self.model_name = model_name

    async def astream_chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """
        Stream the response from the LLM.
        """
        formatted_messages = []
        if system_prompt:
            formatted_messages.append({"role": "system", "content": system_prompt})

        formatted_messages.extend(messages)

        response = await acompletion(
            model=self.model_name,
            messages=formatted_messages,
            stream=True,
            temperature=temperature,
            **kwargs,
        )

        async for chunk in response:
            if chunk.choices and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield delta.content

    async def achat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        """
        Get the full response from the LLM without streaming.
        """
        formatted_messages = []
        if system_prompt:
            formatted_messages.append({"role": "system", "content": system_prompt})

        formatted_messages.extend(messages)

        response = await acompletion(
            model=self.model_name,
            messages=formatted_messages,
            stream=False,
            temperature=temperature,
            **kwargs,
        )

        if response.choices and len(response.choices) > 0:
            return response.choices[0].message.content or ""
        return ""
