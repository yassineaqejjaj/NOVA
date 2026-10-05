"""Fictional project context used by FORGE training scenarios (docs/TRAINING.md).

Training scenarios must exercise every Skill with a realistic project, but they must never carry real ORBIT
content: FORGE stores scenarios and shows them to evaluators. This pack is synthetic, internal (C1) and the
same for every Skill, so scores are comparable across Skills and across cycles. Changing it changes the
scenarios (new content hash) — bump ``PACK_VERSION``.
"""

from __future__ import annotations

PACK_VERSION = "1"
PACK_CLASSIFICATION = 1  # C1 internal — synthetic data only
PROJECT = "Relais"

DOCUMENTS: list[dict[str, str]] = [
    {
        "id": "relais-brief",
        "title": "Relais — product brief",
        "source": "nova-training-pack",
        "content": (
            "Relais is a mobile app for the field technicians of a utility company (3,200 technicians, 14 regions). "
            "Problem: technicians lose 40 minutes a day on paperwork and calls to the back office to close an "
            "intervention; 18% of interventions are closed with missing data, which delays invoicing by 9 days on "
            "average. Goal for the next two quarters: reduce closing time to under 10 minutes and missing-data "
            "closures below 5%. Primary users: field technicians (often offline, gloves, sunlight). Secondary users: "
            "regional dispatchers and the invoicing team. Out of scope: route optimization, payroll. Constraints: "
            "works offline for 8 hours, Android 11+ rugged devices, French and Dutch, GDPR (customer addresses and "
            "phone numbers are personal data)."
        ),
    },
    {
        "id": "relais-research",
        "title": "Relais — field research notes (12 interviews, 2 ride-alongs)",
        "source": "nova-training-pack",
        "content": (
            "Observations: technicians fill the same customer data three times (paper, phone call, legacy form). "
            "Photos of meters are taken with personal phones and sent by messaging apps. Network coverage is absent "
            "in 30% of basements. Quotes: 'I spend my lunch break finishing forms.' 'When the form crashes I lose "
            "everything.' Dispatchers want a live status per intervention. The invoicing team needs the meter reading, "
            "the parts used and the customer signature. Two technicians over 55 struggle with small touch targets."
        ),
    },
    {
        "id": "relais-backlog",
        "title": "Relais — current backlog extract",
        "source": "nova-training-pack",
        "content": (
            "EPIC-1 Offline intervention closing. US-101 As a technician I want to close an intervention offline so "
            "that I can work in basements (priority: must). US-102 As a technician I want to attach meter photos "
            "from the app so that I stop using my personal phone (must). US-103 As a dispatcher I want a live status "
            "per intervention so that I can reassign work (should). US-104 As an invoicing agent I want mandatory "
            "fields validated before closing so that invoices are not delayed (must). EPIC-2 Customer signature. "
            "US-201 As a technician I want to collect the customer's signature on the device (should). Velocity: "
            "about 30 points per two-week sprint, team of 5 developers, 1 designer, 1 QA."
        ),
    },
    {
        "id": "relais-architecture",
        "title": "Relais — architecture and decisions",
        "source": "nova-training-pack",
        "content": (
            "Current state: legacy web form (Java monolith) and a SAP invoicing system with a nightly batch import. "
            "Decision ADR-004 (accepted): the app is native Android (Kotlin) with a local SQLite store and background "
            "sync; conflicts are resolved server-side, last writer wins per field except the meter reading which "
            "requires dispatcher review. Decision ADR-006 (proposed): expose an intervention API (REST, OAuth2) in "
            "front of the monolith. Non-functional targets: sync of a closed intervention under 2 minutes once "
            "online, 99.5% availability of the API during working hours, photos compressed under 500 KB."
        ),
    },
    {
        "id": "relais-delivery",
        "title": "Relais — delivery status and risks",
        "source": "nova-training-pack",
        "content": (
            "Pilot planned in region North (220 technicians) at the start of next quarter. Dependencies: the SAP "
            "team must deliver the intervention import API (not yet scheduled); devices are provided by IT "
            "(order placed, delivery date unknown). Risks: SAP API delay; low adoption by senior technicians; "
            "photo storage costs. Last sprint: 26 of 31 points delivered; offline storage prototype done; sync "
            "conflict handling not started. Stakeholders: VP Field Operations (sponsor), Head of Invoicing, "
            "regional dispatch leads, works council (to be consulted on location tracking)."
        ),
    },
]

EXPECTED_BEHAVIOR = (
    "Produce the deliverable the Skill is meant to produce for the Relais project, grounded in the provided "
    "context and citing it, stating assumptions and open questions instead of inventing facts, metrics, dates "
    "or decisions, and without exposing personal data."
)
