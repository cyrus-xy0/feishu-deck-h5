#!/usr/bin/env python3
"""Validate pitch-rehearsal-simulator output with stdlib-only checks."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


KEY_RE = re.compile(r"^[a-z][a-z0-9-]*$")
MEETING_TYPES = {
    "first-meeting",
    "solution-pitch",
    "poc-kickoff",
    "renewal",
    "investor-pitch",
    "internal-alignment",
    "review",
    "unknown",
}
OUTCOMES = {
    "advance-next-meeting",
    "request-more-material",
    "internal-review",
    "poc-approved",
    "defer",
    "reject",
    "unknown",
}
CONFIDENCE = {"high", "medium", "low"}
PRIORITIES = {"P0", "P1", "P2"}
OWNERS = {"outline", "deck", "talk-track", "evidence", "asset"}
SCORE_KEYS = {"clarity", "urgency", "trust", "feasibility", "next_step_readiness"}


class Validator:
    def __init__(self, path: Path):
        self.path = path
        self.errors: list[str] = []

    def error(self, where: str, message: str) -> None:
        self.errors.append(f"{where}: {message}")

    def require(self, obj: object, where: str, keys: list[str]) -> bool:
        if not isinstance(obj, dict):
            self.error(where, "expected object")
            return False
        ok = True
        for key in keys:
            if key not in obj:
                self.error(where, f"missing required field `{key}`")
                ok = False
        return ok

    def validate(self) -> bool:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - CLI validator should surface parse errors.
            self.error(str(self.path), f"invalid JSON: {exc}")
            return False

        self.require(
            data,
            "$",
            [
                "version",
                "source",
                "meeting",
                "audience_panel",
                "deck_arc",
                "slide_reactions",
                "objection_map",
                "outcome_forecast",
                "revision_queue",
                "talk_track",
                "claim_discipline",
            ],
        )
        if data.get("version") != "1.0":
            self.error("$.version", "must be 1.0")

        self.validate_source(data.get("source"))
        self.validate_meeting(data.get("meeting"))
        persona_ids = self.validate_personas(data.get("audience_panel"))
        slide_keys = self.validate_slide_reactions(data.get("slide_reactions"))
        self.validate_deck_arc(data.get("deck_arc"))
        self.validate_objections(data.get("objection_map"), persona_ids, slide_keys)
        self.validate_outcome(data.get("outcome_forecast"))
        self.validate_revisions(data.get("revision_queue"), slide_keys)
        self.validate_talk_track(data.get("talk_track"))
        self.validate_claims(data.get("claim_discipline"))
        return not self.errors

    def validate_source(self, source: object) -> None:
        if not self.require(source, "$.source", ["artifacts", "assumptions", "limitations"]):
            return
        if not isinstance(source.get("artifacts"), list) or not source.get("artifacts"):
            self.error("$.source.artifacts", "must list at least one input artifact or source")

    def validate_meeting(self, meeting: object) -> None:
        if not self.require(meeting, "$.meeting", ["title", "audience", "objective", "success_next_step", "meeting_type"]):
            return
        if meeting.get("meeting_type") not in MEETING_TYPES:
            self.error("$.meeting.meeting_type", f"must be one of {sorted(MEETING_TYPES)}")

    def validate_personas(self, personas: object) -> set[str]:
        if not isinstance(personas, list) or len(personas) < 3:
            self.error("$.audience_panel", "must contain at least 3 personas")
            return set()
        seen: set[str] = set()
        for i, persona in enumerate(personas):
            where = f"$.audience_panel[{i}]"
            if not self.require(persona, where, ["id", "role", "agenda", "success_criteria", "likely_objections"]):
                continue
            persona_id = persona.get("id")
            if not isinstance(persona_id, str) or not KEY_RE.match(persona_id):
                self.error(f"{where}.id", "must be kebab-case")
                continue
            if persona_id in seen:
                self.error(f"{where}.id", f"duplicate persona id `{persona_id}`")
            seen.add(persona_id)
        return seen

    def validate_deck_arc(self, arc: object) -> None:
        if not self.require(arc, "$.deck_arc", ["summary", "strongest_moment", "weakest_moment", "narrative_risk", "scores"]):
            return
        scores = arc.get("scores")
        if not isinstance(scores, dict):
            self.error("$.deck_arc.scores", "expected object")
            return
        missing = SCORE_KEYS - set(scores)
        if missing:
            self.error("$.deck_arc.scores", f"missing scores: {', '.join(sorted(missing))}")
        for key, value in scores.items():
            if key not in SCORE_KEYS:
                self.error(f"$.deck_arc.scores.{key}", "unknown score")
            elif not isinstance(value, int) or not 0 <= value <= 100:
                self.error(f"$.deck_arc.scores.{key}", "must be integer 0-100")

    def validate_slide_reactions(self, reactions: object) -> set[str]:
        if not isinstance(reactions, list) or not reactions:
            self.error("$.slide_reactions", "must contain at least one slide reaction")
            return set()
        seen: set[str] = set()
        for i, reaction in enumerate(reactions):
            where = f"$.slide_reactions[{i}]"
            if not self.require(
                reaction,
                where,
                ["slide_key", "title", "reaction", "positive_signal", "friction", "likely_questions", "simulated_quote", "revision_hint"],
            ):
                continue
            slide_key = reaction.get("slide_key")
            if not isinstance(slide_key, str) or not KEY_RE.match(slide_key):
                self.error(f"{where}.slide_key", "must be kebab-case")
                continue
            if slide_key in seen:
                self.error(f"{where}.slide_key", f"duplicate slide key `{slide_key}`")
            seen.add(slide_key)
        return seen

    def validate_objections(self, objections: object, persona_ids: set[str], slide_keys: set[str]) -> None:
        if not isinstance(objections, list):
            self.error("$.objection_map", "must be an array")
            return
        for i, objection in enumerate(objections):
            where = f"$.objection_map[{i}]"
            if not self.require(objection, where, ["persona_id", "objection", "trigger_slide_keys", "best_response"]):
                continue
            persona_id = objection.get("persona_id")
            if persona_ids and persona_id not in persona_ids:
                self.error(f"{where}.persona_id", f"unknown persona id `{persona_id}`")
            for slide_key in objection.get("trigger_slide_keys", []) or []:
                if slide_keys and slide_key not in slide_keys:
                    self.error(f"{where}.trigger_slide_keys", f"unknown slide key `{slide_key}`")

    def validate_outcome(self, outcome: object) -> None:
        if not self.require(outcome, "$.outcome_forecast", ["primary_outcome", "confidence", "why", "conditions_to_improve"]):
            return
        if outcome.get("primary_outcome") not in OUTCOMES:
            self.error("$.outcome_forecast.primary_outcome", f"must be one of {sorted(OUTCOMES)}")
        if outcome.get("confidence") not in CONFIDENCE:
            self.error("$.outcome_forecast.confidence", f"must be one of {sorted(CONFIDENCE)}")

    def validate_revisions(self, revisions: object, slide_keys: set[str]) -> None:
        if not isinstance(revisions, list):
            self.error("$.revision_queue", "must be an array")
            return
        for i, revision in enumerate(revisions):
            where = f"$.revision_queue[{i}]"
            if not self.require(revision, where, ["priority", "target", "issue", "change", "owner"]):
                continue
            if revision.get("priority") not in PRIORITIES:
                self.error(f"{where}.priority", f"must be one of {sorted(PRIORITIES)}")
            if revision.get("owner") not in OWNERS:
                self.error(f"{where}.owner", f"must be one of {sorted(OWNERS)}")
            target = revision.get("target")
            if slide_keys and target != "deck-level" and target not in slide_keys:
                self.error(f"{where}.target", f"must be `deck-level` or known slide key, got `{target}`")

    def validate_talk_track(self, talk_track: object) -> None:
        self.require(talk_track, "$.talk_track", ["opening", "transition_notes", "closing_ask", "do_not_say"])

    def validate_claims(self, claims: object) -> None:
        if not self.require(claims, "$.claim_discipline", ["simulated_not_observed", "needs_confirmation", "unsafe_claims_to_remove"]):
            return
        if claims.get("simulated_not_observed") is not True:
            self.error("$.claim_discipline.simulated_not_observed", "must be true")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args(argv)

    ok = True
    for path in args.paths:
        validator = Validator(path)
        if validator.validate():
            print(f"PASS {path}")
            continue
        ok = False
        print(f"FAIL {path}", file=sys.stderr)
        for error in validator.errors:
            print(f"  - {error}", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
