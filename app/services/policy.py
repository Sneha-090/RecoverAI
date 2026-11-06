"""Pure recovery selection, shared by the application and offline evaluation."""


def select_recovery_action(amount, predictions, retry_eligible, retry_reason,
                           excluded_actions=None, *, action_costs, score_floor=0.0,
                           confidence_band_low=0.40, confidence_band_high=0.60,
                           human_review_amount_threshold=50000.0):
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
    best_action = max(scored, key=scored.get)
    best_score, best_prob = scored[best_action], candidates[best_action]
    if best_score <= score_floor:
        return {'chosen_action': None, 'decision_type': 'skip',
                'reason': f'no eligible action scores above floor (best: {best_action} @ {best_score:.2f})'}
    uncertain = confidence_band_low <= best_prob <= confidence_band_high
    high_value = amount > human_review_amount_threshold
    if uncertain or high_value:
        reasons = []
        if uncertain:
            reasons.append(f'confidence {best_prob:.2f} in uncertain band [{confidence_band_low}-{confidence_band_high}]')
        if high_value:
            reasons.append(f'amount {amount} exceeds human-review threshold {human_review_amount_threshold}')
        return {'chosen_action': best_action, 'decision_type': 'human_review', 'reason': '; '.join(reasons)}
    return {'chosen_action': best_action, 'decision_type': 'auto',
            'reason': f'best eligible action {best_action} scored {best_score:.2f} (P={best_prob:.2f}), above threshold and outside uncertain band'}
