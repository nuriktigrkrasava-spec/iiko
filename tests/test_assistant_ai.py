from assistant_ai import rules_advice, _parse_advice


def test_rules_advice_flags_high_foodcost_with_money_and_sorts():
    signals = {"branches": [
        {"name": "Актобе", "foodcost": {"fact_pct": 56.0, "norm_pct": 30, "fact_sum": 500000},
         "revenue": 900000, "cancels": 40000, "writeoffs_pct": 3.0,
         "reviews": [], "peak": None, "has_recipes": True, "has_socials": False},
    ]}
    out = rules_advice(signals)
    # фудкост 56% при норме 30% и отмены 40k → минимум два совета, самый денежный первым
    assert len(out) >= 2
    assert out[0]["money"] >= out[1]["money"]
    fc = next(a for a in out if "удкост" in a["title"] or "удкост" in a["detail"])
    assert fc["branch"] == "Актобе"
    assert fc["action"] == {"type": "navigate", "tab": "fc", "hint": None}


def test_rules_advice_socials_plan_when_not_connected():
    signals = {"branches": [
        {"name": "Актау", "foodcost": None, "revenue": 800000, "cancels": 0,
         "writeoffs_pct": 0, "reviews": [], "peak": None,
         "has_recipes": False, "has_socials": False},
    ]}
    out = rules_advice(signals)
    assert any(a["action"] == {"type": "navigate", "tab": "rep", "hint": None} for a in out)


def test_parse_advice_strips_markdown():
    raw = '```json\n[{"branch":"X","title":"t","detail":"d","money":10,"severity":"low"}]\n```'
    out = _parse_advice(raw)
    assert out[0]["branch"] == "X"
