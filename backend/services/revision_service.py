from __future__ import annotations

from models.survey import SurveyRevisionRequest


class RevisionService:
    def validate_revisions(self, revision_request: SurveyRevisionRequest) -> dict[str, str]:
        revisions: dict[str, str] = {}
        for item in revision_request.revisions:
            section_id = item.section_id.strip()
            feedback = item.feedback.strip()
            if not section_id or not feedback:
                continue
            revisions[section_id] = feedback
        if not revisions:
            raise ValueError("At least one section revision with feedback is required.")
        return revisions
