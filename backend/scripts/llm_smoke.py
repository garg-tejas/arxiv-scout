from __future__ import annotations

import argparse
import asyncio

from pydantic import BaseModel

from app.config import get_settings
from integrations.llm import GLMChatClient, GeminiChatClient, LLMProvider, LLMRole, LLMRouter


class SmokeResponse(BaseModel):
    status: str
    provider: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-check GLM or Gemini text and structured outputs.")
    parser.add_argument("--provider", choices=[provider.value for provider in LLMProvider], required=True)
    parser.add_argument(
        "--prompt",
        default="Reply with a short acknowledgement that the smoke test is running.",
        help="Prompt to send to the provider.",
    )
    parser.add_argument(
        "--structured",
        action="store_true",
        help="Run a structured-output smoke check instead of a plain text check.",
    )
    return parser.parse_args()


def build_router() -> LLMRouter:
    settings = get_settings()
    return LLMRouter(
        glm_client=GLMChatClient(
            base_url=settings.glm_base_url,
            api_key=settings.glm_api_key,
            default_model=settings.glm_model,
            timeout_seconds=settings.llm_timeout_seconds,
        ),
        gemini_client=GeminiChatClient(
            base_url=settings.gemini_base_url,
            api_key=settings.gemini_api_key,
            default_model=settings.gemini_model,
            timeout_seconds=settings.llm_timeout_seconds,
        ),
        max_retries=settings.llm_max_retries,
    )


async def main() -> None:
    args = parse_args()
    router = build_router()
    provider = LLMProvider(args.provider)

    if args.structured:
        result = await router.generate_structured(
            role=LLMRole.SMOKE_TEST,
            provider_override=provider,
            system_prompt=(
                "Return JSON only. "
                "The response must include a status string and a provider string."
            ),
            user_prompt=(
                f"{args.prompt}\n\n"
                f"Set status to 'ok' and provider to '{provider.value}'."
            ),
            schema_type=SmokeResponse,
        )
        print(result.model_dump_json(indent=2))
        return

    result = await router.generate_text(
        role=LLMRole.SMOKE_TEST,
        provider_override=provider,
        system_prompt="Reply with plain text only.",
        user_prompt=args.prompt,
    )
    print(result.text)


if __name__ == "__main__":
    asyncio.run(main())
