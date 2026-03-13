from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Any, TypeVar

from openai import AsyncOpenAI
from pydantic import TypeAdapter, ValidationError

from models.enums import LLMProvider, LLMRole

logger = logging.getLogger(__name__)

SchemaT = TypeVar("SchemaT")


class LLMError(RuntimeError):
    """Raised when an LLM provider call fails."""


class StructuredLLMError(LLMError):
    """Raised when structured output cannot be validated after retries."""


@dataclass(slots=True)
class LLMMessage:
    role: str
    content: str


@dataclass(slots=True)
class ModelRoute:
    provider: LLMProvider
    model: str


@dataclass(slots=True)
class LLMCompletion:
    text: str
    provider: LLMProvider
    model: str
    raw_response: dict[str, Any]


class BaseChatClient:
    provider: LLMProvider

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None,
        default_model: str,
        timeout_seconds: float,
    ) -> None:
        self.base_url = _normalize_base_url(base_url)
        self.api_key = api_key
        self.default_model = default_model
        self.timeout_seconds = timeout_seconds
        self.client: AsyncOpenAI | None = None

    def _require_api_key(self) -> str:
        if not self.api_key:
            raise LLMError(
                f"{self.__class__.__name__} is not configured with an API key."
            )
        return self.api_key

    def _get_client(self) -> AsyncOpenAI:
        if self.client is None:
            self.client = AsyncOpenAI(
                api_key=self._require_api_key(),
                base_url=self.base_url,
                timeout=self.timeout_seconds,
            )
        return self.client

    async def complete(
        self,
        *,
        messages: list[LLMMessage],
        model: str | None = None,
        temperature: float = 0.2,
        response_json_schema: dict[str, Any] | None = None,
    ) -> LLMCompletion:
        request: dict[str, Any] = {
            "model": model or self.default_model,
            "messages": [asdict(message) for message in messages],
            "temperature": temperature,
        }
        if response_json_schema is not None:
            request["response_format"] = {"type": "json_object"}
            schema_instruction = (
                "You MUST respond with valid JSON that conforms to the following JSON schema:\n"
                f"```json\n{json.dumps(response_json_schema, indent=2)}\n```\n"
                "Respond ONLY with the JSON object, no additional text."
            )
            messages_dicts = request["messages"]
            if messages_dicts and messages_dicts[0].get("role") == "system":
                messages_dicts[0]["content"] = (
                    schema_instruction + "\n\n" + messages_dicts[0]["content"]
                )
            else:
                messages_dicts.insert(
                    0, {"role": "system", "content": schema_instruction}
                )

        try:
            completion = await self._get_client().chat.completions.create(**request)
        except Exception as exc:
            logger.error(
                "%s API call failed (model=%s): %s",
                self.provider.value,
                request["model"],
                exc,
            )
            raise LLMError(
                f"{self.provider.value} completion request failed: {exc}"
            ) from exc

        try:
            message = completion.choices[0].message
        except (AttributeError, IndexError) as exc:
            raise LLMError(
                f"{self.provider.value} returned no completion choices: {completion}"
            ) from exc

        text = _coerce_message_content(message.content)
        if not text:
            raise LLMError(
                f"{self.provider.value} returned empty content: {completion.model_dump()}"
            )

        return LLMCompletion(
            text=text,
            provider=self.provider,
            model=request["model"],
            raw_response=completion.model_dump(mode="json"),
        )


class GLMChatClient(BaseChatClient):
    provider = LLMProvider.GLM


class GeminiChatClient(BaseChatClient):
    provider = LLMProvider.GEMINI


class LLMRouter:
    def __init__(
        self,
        *,
        glm_client: GLMChatClient,
        gemini_client: GeminiChatClient,
        max_retries: int,
    ) -> None:
        self.glm_client = glm_client
        self.gemini_client = gemini_client
        self.max_retries = max_retries
        self.role_routes: dict[LLMRole, ModelRoute] = {
            LLMRole.SEARCH: ModelRoute(LLMProvider.GLM, glm_client.default_model),
            LLMRole.CURATION: ModelRoute(LLMProvider.GLM, glm_client.default_model),
            LLMRole.STEERING: ModelRoute(LLMProvider.GLM, glm_client.default_model),
            LLMRole.PAPER_ANALYZER: ModelRoute(
                LLMProvider.GLM, glm_client.default_model
            ),
            LLMRole.SURVEY_ORCHESTRATOR: ModelRoute(
                LLMProvider.GLM, glm_client.default_model
            ),
            LLMRole.THEMATIC_CLUSTERING: ModelRoute(
                LLMProvider.GLM, glm_client.default_model
            ),
            LLMRole.SECTION_REVIEWER: ModelRoute(
                LLMProvider.GLM, glm_client.default_model
            ),
            LLMRole.SURVEY_ASSEMBLER: ModelRoute(
                LLMProvider.GLM, glm_client.default_model
            ),
            LLMRole.SECTION_WRITER: ModelRoute(
                LLMProvider.GEMINI, gemini_client.default_model
            ),
            LLMRole.SMOKE_TEST: ModelRoute(LLMProvider.GLM, glm_client.default_model),
        }

    def get_route(
        self, role: LLMRole, *, provider_override: LLMProvider | None = None
    ) -> ModelRoute:
        route = self.role_routes[role]
        if provider_override is None:
            return route
        if provider_override == LLMProvider.GEMINI:
            return ModelRoute(provider_override, self.gemini_client.default_model)
        return ModelRoute(provider_override, self.glm_client.default_model)

    def _fallback_provider(self, primary: LLMProvider) -> LLMProvider:
        """Return the alternate provider for fallback."""
        if primary == LLMProvider.GEMINI:
            return LLMProvider.GLM
        return LLMProvider.GEMINI

    async def generate_text(
        self,
        *,
        role: LLMRole,
        user_prompt: str,
        system_prompt: str | None = None,
        temperature: float = 0.2,
        provider_override: LLMProvider | None = None,
        model_override: str | None = None,
    ) -> LLMCompletion:
        route = self.get_route(role, provider_override=provider_override)
        client = self._get_client(route.provider)
        try:
            return await client.complete(
                messages=_build_messages(
                    system_prompt=system_prompt, user_prompt=user_prompt
                ),
                model=model_override or route.model,
                temperature=temperature,
            )
        except LLMError:
            if provider_override is not None:
                raise  # caller explicitly chose a provider; don't second-guess
            fallback_provider = self._fallback_provider(route.provider)
            fallback_route = self.get_route(role, provider_override=fallback_provider)
            fallback_client = self._get_client(fallback_provider)
            logger.warning(
                "LLM provider %s failed for role %s; falling back to %s",
                route.provider.value,
                role.value,
                fallback_provider.value,
            )
            return await fallback_client.complete(
                messages=_build_messages(
                    system_prompt=system_prompt, user_prompt=user_prompt
                ),
                model=fallback_route.model,
                temperature=temperature,
            )

    async def generate_structured(
        self,
        *,
        role: LLMRole,
        user_prompt: str,
        schema_type: Any,
        system_prompt: str | None = None,
        temperature: float = 0.1,
        provider_override: LLMProvider | None = None,
        model_override: str | None = None,
    ) -> SchemaT:
        try:
            return await self._generate_structured_inner(
                role=role,
                user_prompt=user_prompt,
                schema_type=schema_type,
                system_prompt=system_prompt,
                temperature=temperature,
                route=self.get_route(role, provider_override=provider_override),
                model_override=model_override,
            )
        except LLMError:
            if provider_override is not None:
                raise
            fallback_provider = self._fallback_provider(
                self.get_route(role).provider,
            )
            fallback_route = self.get_route(role, provider_override=fallback_provider)
            logger.warning(
                "LLM provider %s failed for structured role %s; falling back to %s",
                self.get_route(role).provider.value,
                role.value,
                fallback_provider.value,
            )
            return await self._generate_structured_inner(
                role=role,
                user_prompt=user_prompt,
                schema_type=schema_type,
                system_prompt=system_prompt,
                temperature=temperature,
                route=fallback_route,
                model_override=None,
            )

    async def _generate_structured_inner(
        self,
        *,
        role: LLMRole,
        user_prompt: str,
        schema_type: Any,
        system_prompt: str | None,
        temperature: float,
        route: ModelRoute,
        model_override: str | None,
    ) -> SchemaT:
        adapter: TypeAdapter[SchemaT] = TypeAdapter(schema_type)
        schema = adapter.json_schema()
        client = self._get_client(route.provider)
        model_name = model_override or route.model
        attempt_prompt = user_prompt
        validation_error: ValidationError | None = None

        for attempt in range(self.max_retries + 1):
            completion = await client.complete(
                messages=_build_messages(
                    system_prompt=system_prompt, user_prompt=attempt_prompt
                ),
                model=model_name,
                temperature=temperature,
                response_json_schema=schema,
            )
            try:
                return adapter.validate_json(completion.text)
            except ValidationError as exc:
                validation_error = exc
                if attempt >= self.max_retries:
                    break
                attempt_prompt = (
                    f"{user_prompt}\n\n"
                    "Your previous response failed schema validation. "
                    "Return only valid JSON matching the schema.\n\n"
                    f"Validation error:\n{exc}"
                )

        error_msg = (
            "Structured output validation failed after retry attempts."
            if validation_error is None
            else f"Structured output validation failed after retry attempts: {validation_error}"
        )
        logger.error(
            "Structured output exhausted retries for role %s (provider=%s): %s",
            role.value,
            client.provider.value,
            error_msg,
        )
        raise StructuredLLMError(error_msg)

    def _get_client(self, provider: LLMProvider) -> BaseChatClient:
        if provider == LLMProvider.GEMINI:
            return self.gemini_client
        return self.glm_client


def _build_messages(*, system_prompt: str | None, user_prompt: str) -> list[LLMMessage]:
    messages: list[LLMMessage] = []
    if system_prompt:
        messages.append(LLMMessage(role="system", content=system_prompt))
    messages.append(LLMMessage(role="user", content=user_prompt))
    return messages


def _normalize_base_url(value: str) -> str:
    return value.rstrip("/") + "/"


def _coerce_message_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            text = getattr(item, "text", None)
            if isinstance(text, str):
                parts.append(text)
                continue
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts).strip()
    return str(content).strip() if content is not None else ""
