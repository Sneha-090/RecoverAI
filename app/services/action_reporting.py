"""Descriptive recorded decision counts; never infer effectiveness or bias from counts."""

from collections import Counter

from app.models.models import Action, Diagnosis, Payment


SCOPES = {'Razorpay Test Mode': 'pay_', 'Simulation': 'sim_'}
ACTIONS = ('retry', 'payment_link', 'alt_method')
MISSING_CAUSE = 'Not recorded'


def build_action_report(db, scope='Razorpay Test Mode', cause=None):
    if scope not in SCOPES:
        raise ValueError('Choose a supported data source')
    payments = db.query(Payment).filter(
        Payment.payment_id.startswith(SCOPES[scope], autoescape=True),
    ).all()
    ids = [p.payment_id for p in payments]
    diagnoses = db.query(Diagnosis).filter(Diagnosis.payment_id.in_(ids)).order_by(
        Diagnosis.diagnosed_at, Diagnosis.id,
    ).all() if ids else []
    causes = {p.payment_id: MISSING_CAUSE for p in payments}
    causes.update({row.payment_id: row.cause for row in diagnoses})
    available_causes = sorted(set(causes.values()))
    if cause is not None:
        payments = [p for p in payments if causes[p.payment_id] == cause]
    ids = {p.payment_id for p in payments}
    actions = db.query(Action).filter(Action.payment_id.in_(ids)).order_by(
        Action.chosen_at, Action.id,
    ).all() if ids else []
    first = {}
    for row in actions:
        first.setdefault(row.payment_id, row)
    first_counts = Counter(row.action_type for row in first.values())
    executed = [row for row in actions if row.decision_type.value == 'auto']
    executed_counts = Counter(row.action_type for row in executed)
    approved_counts = Counter(row.action_type for row in executed
                              if (row.reason or '').startswith('human-approved action'))
    pending = {row.payment_id for row in actions if row.review_status is not None
               and row.review_status.value == 'pending'}
    labels = [*ACTIONS, *sorted((set(first_counts)|set(executed_counts))-set(ACTIONS))]
    distribution = [{
        'Action': label,
        'First recorded decisions': first_counts[label],
        'Share of first decisions': first_counts[label] / len(first) if first else 0.0,
        'Recorded executions': executed_counts[label],
        'Human-approved executions': approved_counts[label],
    } for label in labels]
    by_cause = []
    for label in sorted({causes[p.payment_id] for p in payments}):
        case_ids = {p.payment_id for p in payments if causes[p.payment_id] == label}
        choices = Counter(first[pid].action_type for pid in case_ids if pid in first)
        by_cause.append({'Recorded cause': label, 'Cases': len(case_ids),
                         'Cases without a recorded decision': len(case_ids-set(first)),
                         **{action: choices[action] for action in labels}})
    recovered = [p for p in payments if p.status == 'recovered']
    return {'scope': scope, 'available_causes': available_causes,
            'cases': len(payments), 'recovered_cases': len(recovered),
            'recovered_amount': round(sum(p.amount for p in recovered), 2),
            'first_decisions': len(first), 'cases_without_decision': len(payments)-len(first),
            'pending_review_cases': len(pending), 'executions': len(executed),
            'distribution': distribution, 'by_cause': by_cause}
