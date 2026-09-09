#!/usr/bin/env python3
"""The half a rule cannot score: is the talking point any good, judged, against a floor.

Everything in ``run_eval.py`` is deterministic and binary. Is every point grounded. Does every
citation resolve to a house view that was actually retrieved. Is the theme suitable for this
client. Did anything advice-shaped or personal survive. Those are questions code can answer, and
code answers them there.

They leave a gap, and it is what a relationship manager actually reads out. A talking point can
be grounded, correctly cited, suitable and free of both advice and personal data, and still fail
to say what the house view means, state a condition as a certainty, or read as a decision the
client has already taken. Deciding that is a judgement, so it is judged, and the judge is held to
the same standard as every other scorer here: it must be shown able to fail before anything it
certifies is believed.

The whole run is ``agent_eval_kit.narrative_main``. This file supplies only what is specific to
this service: where the table is, where the floors are, the profiles each point is written in,
and which of them is the deliberate control.

    make eval-narrative     # offline, no model, no credentials, no network

The judge is chosen HERE, on the command line, and never from the environment: a gate whose
scorer a stray variable could swap is not a gate.
"""

from __future__ import annotations

import sys
from pathlib import Path

from agent_eval_kit import narrative_main

_REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET = _REPO_ROOT / "eval" / "datasets" / "narrative_golden.jsonl"
FLOORS = _REPO_ROOT / "config" / "quality-floors.toml"

#: The three ways each talking point is written. Profiles rather than adjectives: they name
#: WHICH deployment produced the prose, which is what a portability claim is about.
PROFILES = ("managed", "reduced", "regressed")

#: The control. It exists to sit below the floor, so a table where it passes is a table whose
#: floor is too low to refuse anything.
CONTROL = "regressed"


if __name__ == "__main__":
    raise SystemExit(
        narrative_main(
            dataset=DATASET,
            floors=FLOORS,
            profiles=PROFILES,
            control=CONTROL,
            description="Briefing narrative quality, judged against the model-risk floors.",
            argv=sys.argv[1:],
        )
    )
