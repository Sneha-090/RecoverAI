"""Pure expected-value ranking with explicit business review guards.

The action margin is not statistical model confidence. Its default is an
up-front business setting, not a threshold fitted to held-out outcomes.
"""

import math


def select_recovery_action(amount, predictions, retry_eligible, retry_reason,
                           excluded_actions=None, *, action_costs, score_floor=0.0,
                           min_action_margin_ratio=0.02,
                           human_review_amount_threshold=50000.0):
    if not math.isfinite(amount) or amount <= 0:
        raise ValueError('A positive finite amount is required')
    if min_action_margin_ratio is not None and not 0 <= min_action_margin_ratio <= 1:
        raise ValueError('Action review margin must be between zero and one')
    if any(action not in action_costs or not math.isfinite(probability) or not 0 <= probability <= 1
           for action, probability in predictions.items()):
        raise ValueError('Predictions require supported actions and finite probabilities between zero and one')
    excluded_actions = excluded_actions or set()
    candidates = {action: probability for action, probability in predictions.items()
                  if action not in excluded_actions}
    if not retry_eligible:
        candidates.pop('retry', None)
    if not candidates:
        reason = retry_reason if not retry_eligible else 'all candidate actions already tried'
        return {'chosen_action': None, 'decision_type': 'skip',
                'reason': f'no action remains eligible ({reason})'}
    scored = {action: probability * amount - action_costs[action]
              for action, probability in candidates.items()}
    ranking = sorted(scored, key=scored.get, reverse=True)
    best_action = ranking[0]
    best_score, best_prob = scored[best_action], candidates[best_action]
    if best_score <= score_floor:
        return {'chosen_action': None, 'decision_type': 'skip',
                'reason': f'no eligible action scores above floor (best: {best_action} @ {best_score:.2f})'}
    margin = best_score-scored[ranking[1]] if len(ranking)>1 else None
    near_tie = (margin is not None and min_action_margin_ratio is not None
                and margin <= min_action_margin_ratio*amount + 1e-9)
    high_value = amount > human_review_amount_threshold
    if near_tie or high_value:
        reasons = []
        if near_tie:
            reasons.append(f'top two eligible net-value estimates differ by Rs.{margin:.2f} '
                           f'({margin/amount:.2%} of amount), within the configured '
                           f'{min_action_margin_ratio:.2%} review margin; this is not statistical confidence')
        if high_value:
            reasons.append(f'amount {amount} exceeds human-review threshold {human_review_amount_threshold}')
        return {'chosen_action': best_action, 'decision_type': 'human_review', 'reason': '; '.join(reasons)}
    return {'chosen_action': best_action, 'decision_type': 'auto',
            'reason': f'best eligible action {best_action} scored {best_score:.2f} '
                      f'(estimated success probability={best_prob:.2f}), above floor and review guards passed'}
