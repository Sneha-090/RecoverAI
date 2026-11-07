from types import SimpleNamespace

from app.services.decision import decide_from_predictions, score_action
from app.config import settings


def make_payment(amount):
    return SimpleNamespace(amount=amount)


def test_1_auto_execute_well_separated_values():
    p = make_payment(1000)
    preds = {"retry": 0.85, "payment_link": 0.30, "alt_method": 0.20}
    result = decide_from_predictions(p, preds, retry_eligible=True, retry_reason="retry eligible")
    assert result["decision_type"] == "auto"
    assert result["chosen_action"] == "retry"


def test_2_human_review_near_tied_values():
    p = make_payment(1000)
    preds = {"retry": 0.50, "payment_link": 0.49, "alt_method": 0.20}
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


def test_7_margin_exactly_at_boundary_requires_review():
    p = make_payment(1000)
    preds = {"retry": .5, "payment_link": .49, "alt_method": .1}
    result = decide_from_predictions(p, preds, True, 'eligible')
    assert result['decision_type'] == 'human_review'
    assert 'not statistical confidence' in result['reason']


def test_8_probability_near_half_is_not_itself_uncertainty():
    p = make_payment(1000)
    preds = {"retry": .5, "payment_link": .2, "alt_method": .1}
    assert decide_from_predictions(p, preds, True, 'eligible')['decision_type'] == 'auto'


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


def test_margin_uses_eligible_actions_only():
    result = decide_from_predictions(make_payment(1000),
        {'retry':.81,'payment_link':.8,'alt_method':.1}, False, 'retry blocked')
    assert result['chosen_action']=='payment_link' and result['decision_type']=='auto'


def test_single_remaining_candidate_has_no_artificial_runner_up():
    result = decide_from_predictions(make_payment(1000), {'payment_link':.5}, True, 'eligible')
    assert result['decision_type']=='auto'


import pytest
from app.services.policy import select_recovery_action


@pytest.mark.parametrize('probability', [float('nan'),float('inf'),-0.1,1.1])
def test_invalid_probability_cannot_authorize_an_action(probability):
    with pytest.raises(ValueError):
        select_recovery_action(499, {'retry':probability}, True, 'eligible', action_costs={'retry':5})
