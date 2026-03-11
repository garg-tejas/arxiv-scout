from __future__ import annotations


class ModelRegistry:
    def get_primary_model(self) -> str:
        return "gemini-2.0-flash"

    def get_fallback_model(self) -> str:
        return "glm-4.7-flash"
