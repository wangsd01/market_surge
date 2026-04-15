from __future__ import annotations

import json
from pathlib import Path

from decision_tickets import DecisionTicket, ticket_to_dict


def _ticket() -> DecisionTicket:
    return DecisionTicket(
        rank=1,
        ticker="AAA",
        pattern="cup_handle",
        entry=10.0,
        stop=9.0,
        target=12.0,
        risk_per_share=1.0,
        shares=100,
        position_value=1000.0,
        score=0.87,
        summary_reason="clean setup",
        invalidation_rule="invalid if price trades below stop",
        sizing_basis={
            "account_size": 10_000.0,
            "risk_pct": 0.01,
            "risk_dollars": 100.0,
            "max_position_dollars": None,
        },
    )


def test_decision_ticket_schema_matches_serialized_output():
    schema = json.loads(Path("schemas/decision_ticket_v1.json").read_text())
    payload = ticket_to_dict(_ticket())

    assert schema["type"] == "object"
    assert set(schema["required"]) == set(payload.keys())
    assert set(schema["properties"].keys()) == set(payload.keys())
    assert schema["properties"]["rank"]["type"] == "integer"
    assert schema["properties"]["ticker"]["type"] == "string"
    assert schema["properties"]["sizing_basis"]["type"] == "object"
    assert set(schema["properties"]["sizing_basis"]["required"]) == {
        "account_size",
        "risk_pct",
        "risk_dollars",
        "max_position_dollars",
    }
