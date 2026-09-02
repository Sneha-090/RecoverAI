from types import SimpleNamespace

from app.services.decision import decide_from_predictions, score_action
from app.config import settings


def make_payment(amount):
    return SimpleNamespace(amount=amount)


def test_1_auto_execute_high_confidence_low_amount():
    p = make_payment(1000)
    preds = {"retry": 0.85, "payment_link": 0.30, "alt_method": 0.20}
    result = decide_from_predictions(p, preds, retry_eligible=True, retry_reason="retry eligible")
    assert result["decision_type"] == "auto"
    assert result["chosen_action"] == "retry"


def test_2_human_review_confidence_in_band():
    p = make_payment(1000)
    preds = {"retry": 0.50, "payment_link": 0.30, "alt_method": 0.20}
    result = decide_from_predictions(p, preds, retry_eligible=True, retry_reason="retry eligible")
    assert result["decision_type"] == "human_review"
    assert result["chosen_action"] == "retry"


def test_3_human_review_high_value_even_if_confident():
    p = make_payment(60000)
    preds = {"retry": 0.90, "payment_link": 0.30, "alt_method": 0.20}
    result = decide_from_predictions(p, preds, retry_eligible=True, retry_reason="retry eligible")
    assert result["decision_type"] == "human_review"


def test_4_halted_subscription_retry_ineligible_falls_back():
    p = make_payment(1000)
    preds = {"retry": 0.95, "payment_link": 0.80, "alt_method": 0.20}
    result = decide_from_predictions(
        p, preds, retry_eligible=False,
        retry_reason="retry not attempted: subscription in halted state, card update required",
    )
    assert result["chosen_action"] == "payment_link"
    assert result["decision_type"] == "auto"


def test_5_all_actions_score_below_floor_skips():
    p = make_payment(50)
    preds = {"retry": 0.05, "payment_link": 0.05, "alt_method": 0.05}
    result = decide_from_predictions(p, preds, retry_eligible=True, retry_reason="retry eligible")
    assert result["decision_type"] == "skip"
    assert result["chosen_action"] is None


def test_6_no_candidates_when_only_ineligible_retry_predicted():
    p = make_payment(1000)
    preds = {"retry": 0.90}
    result = decide_from_predictions(
        p, preds, retry_eligible=False,
        retry_reason="retry not attempted: max retry attempts (3) already used",
    )
    assert result["decision_type"] == "skip"
    assert result["chosen_action"] is None
    assert "max retry attempts" in result["reason"]


def test_7_boundary_confidence_exactly_at_lower_band_edge():
    p = make_payment(1000)
    preds = {"retry": 0.40, "payment_link": 0.10, "alt_method": 0.10}
    result = decide_from_predictions(p, preds, retry_eligible=True, retry_reason="retry eligible")
    assert result["decision_type"] == "human_review"


def test_8_boundary_confidence_exactly_at_upper_band_edge():
    p = make_payment(1000)
    preds = {"retry": 0.60, "payment_link": 0.10, "alt_method": 0.10}
    result = decide_from_predictions(p, preds, retry_eligible=True, retry_reason="retry eligible")
    assert result["decision_type"] == "human_review"


def test_9_amount_exactly_at_threshold_is_not_high_value():
    p = make_payment(settings.human_review_amount_threshold)
    preds = {"retry": 0.85, "payment_link": 0.10, "alt_method": 0.10}
    result = decide_from_predictions(p, preds, retry_eligible=True, retry_reason="retry eligible")
    assert result["decision_type"] == "auto"


def test_10_best_action_chosen_by_score_not_raw_probability():
    p = make_payment(1000)
    # payment_link has slightly HIGHER probability, but its higher cost (15 vs 5)
    # makes retry's cost-adjusted score win - proving score decides, not raw probability.
    preds = {"retry": 0.850, "payment_link": 0.855, "alt_method": 0.10}
    result = decide_from_predictions(p, preds, retry_eligible=True, retry_reason="retry eligible")
    assert result["chosen_action"] == "retry"