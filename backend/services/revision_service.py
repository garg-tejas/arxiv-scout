from __future__ import annotations

from models.survey import SurveyRevisionRequest


class RevisionService:
    def validate_revisions(self, revision_request: SurveyRevisionRequest) -> dict[str, str]:
        return {item.section_id: item.feedback for item in revision_request.revisions}
