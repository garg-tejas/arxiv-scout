from __future__ import annotations

from models.enums import ArtifactStatusValue, ArtifactType


class ArtifactService:
    def build_initial_artifact_status(self) -> dict[str, ArtifactStatusValue]:
        return {artifact.value: ArtifactStatusValue.PENDING for artifact in ArtifactType}
