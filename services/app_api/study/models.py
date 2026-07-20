"""Pydantic models for the study API and the study-config shape.

Questionnaire items are intentionally generic (rendered by a single component on
the frontend) so researchers can finalize the exact items later without code
changes. Models allow extra fields for the same reason.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ScenarioCard(BaseModel):
    role: str = ""
    task_goal: str = ""
    relevant_facts: str = ""
    success_criteria: str = ""

    class Config:
        extra = "allow"


class QuestionnaireItem(BaseModel):
    id: str
    type: Literal["likert", "scale", "text", "radio", "checkbox", "boolean"] = "text"
    label: str = ""
    options: Optional[list[str]] = None
    required: bool = False
    # likert/scale bounds
    min: Optional[int] = None
    max: Optional[int] = None
    min_label: Optional[str] = None
    max_label: Optional[str] = None

    class Config:
        extra = "allow"


class Condition(BaseModel):
    idx: int
    scenario: ScenarioCard = Field(default_factory=ScenarioCard)
    system_prompt: str = ""
    voice_mode: Literal["natural", "vc"] = "vc"
    target_ref: Optional[str] = None          # references a target row's `ref`
    voice_prompt: Optional[str] = None        # PersonaPlex output voice (.pt); default applied server-side
    steps: int = 8
    time_limit_s: int = 300

    class Config:
        extra = "allow"


class Questionnaires(BaseModel):
    consent: list[QuestionnaireItem] = Field(default_factory=list)
    background: list[QuestionnaireItem] = Field(default_factory=list)
    post: list[QuestionnaireItem] = Field(default_factory=list)
    final: list[QuestionnaireItem] = Field(default_factory=list)

    class Config:
        extra = "allow"


class StudyConfig(BaseModel):
    name: str = "Study"
    default_voice_prompt: str = "NATF2.pt"
    conditions: list[Condition] = Field(default_factory=list)
    questionnaires: Questionnaires = Field(default_factory=Questionnaires)

    class Config:
        extra = "allow"


# --- request bodies ---
class EnterRequest(BaseModel):
    code: str


class RunStartRequest(BaseModel):
    code: str
    mode: Literal["resume", "restart"] = "resume"


class ProgressRequest(BaseModel):
    code: str
    current_step: dict[str, Any] = Field(default_factory=dict)
    completed: dict[str, Any] = Field(default_factory=dict)


class SessionStartRequest(BaseModel):
    code: str
    scenario_order: int


class QuestionnaireRequest(BaseModel):
    code: str
    kind: Literal["consent", "background", "post", "final"]
    payload: dict[str, Any] = Field(default_factory=dict)
    session_id: Optional[str] = None


class EndRequest(BaseModel):
    reason: Literal["goal_reached", "give_up", "technical_problem"]


class SubmitRequest(BaseModel):
    code: str


class GenerateRequest(BaseModel):
    count: int = 1


def default_config() -> dict:
    """A minimal working study so a fresh install can be exercised end-to-end.
    Researchers overwrite this via the admin dashboard; questionnaire items are
    placeholders to be finalized once the protocol is set."""
    consent = [
        QuestionnaireItem(id="consent_participation", type="boolean",
                          label="I consent to participate in this study.", required=True),
        QuestionnaireItem(id="consent_audio", type="boolean",
                          label="I consent to my audio being recorded and saved.", required=True),
        QuestionnaireItem(id="consent_logs", type="boolean",
                          label="I consent to transcripts and interaction logs being saved.", required=True),
    ]
    background = [
        QuestionnaireItem(id="age", type="text", label="Age", required=False),
        QuestionnaireItem(id="native_language", type="text", label="Native language", required=False),
        QuestionnaireItem(id="voice_assistant_use", type="radio", label="How often do you use voice assistants?",
                          options=["Never", "Rarely", "Monthly", "Weekly", "Daily"]),
    ]
    post = [
        QuestionnaireItem(id="understanding", type="likert", label="The system understood me.",
                          min=1, max=7, min_label="Strongly disagree", max_label="Strongly agree"),
        QuestionnaireItem(id="turn_taking", type="likert", label="Turn-taking felt natural.",
                          min=1, max=7, min_label="Strongly disagree", max_label="Strongly agree"),
        QuestionnaireItem(id="effort", type="likert", label="The interaction required little effort.",
                          min=1, max=7, min_label="Strongly disagree", max_label="Strongly agree"),
        QuestionnaireItem(id="trust", type="likert", label="I trusted the system.",
                          min=1, max=7, min_label="Strongly disagree", max_label="Strongly agree"),
        QuestionnaireItem(id="perceived_success", type="likert", label="I achieved the task goal.",
                          min=1, max=7, min_label="Strongly disagree", max_label="Strongly agree"),
        QuestionnaireItem(id="comments", type="text", label="Any comments about this interaction?"),
    ]
    final = [
        QuestionnaireItem(id="overall_turn_taking", type="likert", label="Overall, turn-taking was good.",
                          min=1, max=7, min_label="Strongly disagree", max_label="Strongly agree"),
        QuestionnaireItem(id="usability", type="likert", label="The system was easy to use.",
                          min=1, max=7, min_label="Strongly disagree", max_label="Strongly agree"),
        QuestionnaireItem(id="voice_differences", type="text",
                          label="Did you notice differences between the voices? Describe."),
        QuestionnaireItem(id="overall_comments", type="text", label="Overall comments"),
    ]
    conditions = [
        Condition(idx=i, voice_mode="vc", target_ref=f"vc{i}", steps=8, time_limit_s=300,
                  system_prompt="You are a helpful conversational partner. Keep replies concise.",
                  scenario=ScenarioCard(
                      role=f"Participant role for scenario {i}",
                      task_goal=f"Task goal for scenario {i}",
                      relevant_facts="Relevant facts go here.",
                      success_criteria="Success criteria go here."))
        for i in range(1, 5)
    ]
    return StudyConfig(name="Pilot Study", conditions=conditions,
                       questionnaires=Questionnaires(consent=consent, background=background,
                                                     post=post, final=final)).model_dump()
