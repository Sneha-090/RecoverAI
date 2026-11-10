"""Reviewed reconciliation: provider reads only; never create or retry a charge."""

from datetime import datetime
from uuid import uuid4
import json
import re

from app.models.models import (Action, AuditLog, DecisionType, Payment, RecoveryExecution,
                               RecoveryIntent, RecoveryReservation)
from app.services.execution import _observe_outcome
from app.services.execution_records import amount_paise, record_execution
from app.services.razorpay_client import client
from app.services.reservations import finish_recovery


class ReconciliationError(ValueError):
    pass


def list_stuck_cases(db, limit=50):
    return [{"payment_id": claim.payment_id, "state": claim.state,
             "updated_at": claim.updated_at.isoformat(), "amount": payment.amount}
            for claim, payment in db.query(RecoveryReservation, Payment).join(
                Payment, Payment.payment_id == RecoveryReservation.payment_id).filter(
                RecoveryReservation.state.in_(["processing", "needs_reconciliation"])
            ).order_by(RecoveryReservation.updated_at, RecoveryReservation.payment_id).limit(limit).all()]


def reconciliation_references(db, payment_id):
    references = []
    for row in db.query(RecoveryExecution).filter_by(payment_id=payment_id).order_by(RecoveryExecution.id).all():
        references.append({"key": f"execution:{row.id}", "kind": row.provider_type,
                           "provider_id": row.provider_id, "amount_paise": row.amount_paise})
    for row in db.query(RecoveryIntent).filter_by(payment_id=payment_id, execution_id=None).order_by(RecoveryIntent.created_at).all():
        references.append({"key": f"intent:{row.id}", "kind": row.provider_type,
                           "provider_id": row.provider_id, "amount_paise": None})
    return references


def _reference(db, payment_id, reference_key, supplied_provider_id=None):
    payment = db.get(Payment, payment_id)
    if payment is None or not isinstance(reference_key, str):
        raise ReconciliationError("Payment or reference not found.")
    prefix, _, identity = reference_key.partition(":")
    if prefix == "execution" and identity.isdigit():
        reference = db.get(RecoveryExecution, int(identity))
    elif prefix == "intent":
        reference = db.get(RecoveryIntent, identity)
    else:
        raise ReconciliationError("Unknown recovery reference.")
    if reference is None or reference.payment_id != payment_id:
        raise ReconciliationError("Reference does not belong to this case.")
    if isinstance(reference, RecoveryIntent) and reference.execution_id is not None:
        execution = db.get(RecoveryExecution, reference.execution_id)
        if execution is None or execution.payment_id != payment_id:
            raise ReconciliationError("Execution binding needs manual investigation.")
        reference = execution
    resource_id = reference.provider_id or supplied_provider_id
    if supplied_provider_id and reference.provider_id and supplied_provider_id != reference.provider_id:
        raise ReconciliationError("The stored provider reference cannot be replaced.")
    provider_type = reference.provider_type
    pattern = r"order_[A-Za-z0-9_]{1,100}" if provider_type == "order" else r"plink_[A-Za-z0-9_]{1,100}"
    if not isinstance(resource_id, str) or not re.fullmatch(pattern, resource_id):
        raise ReconciliationError("Enter the matching Razorpay order or payment link ID.")
    return payment, reference, resource_id


def check_reconciliation_status(db, payment_id, reference_key, supplied_provider_id=None):
    """No database writes. Evidence is displayed to the operator, never trusted on apply."""
    payment, reference, resource_id = _reference(db, payment_id, reference_key, supplied_provider_id)
    kind = reference.provider_type
    expected_amount = reference.amount_paise if isinstance(reference, RecoveryExecution) else amount_paise(payment.amount)
    currency = reference.currency if isinstance(reference, RecoveryExecution) else "INR"
    resource = client.order.fetch(resource_id) if kind == "order" else client.payment_link.fetch(resource_id)
    if (not isinstance(resource, dict) or resource.get("id") != resource_id
            or resource.get("amount") != expected_amount or resource.get("currency") != currency):
        raise ReconciliationError("Provider ID, amount or currency does not match this case.")
    if isinstance(reference, RecoveryIntent):
        notes = resource.get("notes")
        if not isinstance(notes, dict) or notes.get("recoverai_intent_id") != reference.id:
            raise ReconciliationError("Provider reference is not verified for this recovery intent.")
    if kind == "order":
        items = client.order.payments(resource_id).get("items", [])
        captured = [item for item in items if item.get("status") == "captured"]
        if captured and not any(item.get("amount") == expected_amount and item.get("currency") == currency
                                and item.get("order_id") == resource_id for item in captured):
            raise ReconciliationError("Captured payment does not match the recovery order.")
        result = "success" if captured else "failed" if items and all(item.get("status") == "failed" for item in items) else "pending"
    else:
        if resource.get("status") == "paid" and resource.get("amount_paid") != expected_amount:
            raise ReconciliationError("The recovery link has not been paid in full.")
        result = "success" if resource.get("status") == "paid" else "failed" if resource.get("status") in {"expired", "cancelled"} else "pending"
    return {"result": result, "provider_status": resource.get("status", "unknown"),
            "provider_id": resource_id, "provider_type": kind, "amount_paise": expected_amount,
            "currency": currency, "checked_at": datetime.utcnow().isoformat() + "Z"}


def _bind_verified_intent(db, payment, intent, provider_id):
    # A DB failure can occur before OR after the executed Action was saved.
    actions = db.query(Action).filter(Action.payment_id == payment.payment_id,
        Action.decision_type == DecisionType.auto, Action.chosen_at >= intent.created_at).all()
    if len(actions) > 1 or (actions and actions[0].action_type != intent.action_type):
        raise ReconciliationError("Ambiguous action history needs manual investigation.")
    action = actions[0] if actions else Action(payment_id=payment.payment_id,
        action_type=intent.action_type, decision_type=DecisionType.auto,
        chosen_at=intent.created_at, reason="Existing provider resource verified during reconciliation")
    if action.id and db.query(RecoveryExecution).filter_by(action_id=action.id).first():
        raise ReconciliationError("Action is already bound to another provider resource.")
    db.add(action)
    db.flush()
    payload = {"type": intent.provider_type,
               "order_id" if intent.provider_type == "order" else "payment_link_id": provider_id}
    if intent.action_type == "alt_method" and intent.provider_type == "payment_link":
        resource = client.payment_link.fetch(provider_id)
        excluded = resource.get("notes", {}).get("recoverai_excluded_method")
        if not excluded:
            raise ReconciliationError("Alternate-method resource has no verified method policy; investigate before settlement.")
        if excluded:
            from app.services.payment_methods import alternate_methods
            excluded, allowed = alternate_methods(excluded)
            payload.update(excluded_method=excluded, available_methods=allowed)
    audit = AuditLog(payment_id=payment.payment_id, event_type="executed",
                     reason="Bound existing provider resource after operator verification",
                     payload_json=json.dumps(payload))
    db.add(audit)
    db.flush()
    execution = record_execution(db, payment, action, audit, payload)
    intent.provider_id, intent.execution_id, intent.state = provider_id, execution.id, "bound"
    return execution


def reconcile_verified_success(db, payment_id, reference_key, operator_username, supplied_provider_id=None):
    """Re-check evidence under an exclusive claim. Only a verified success settles.

    Never take over a processing claim, expire a claim, replay an uncertain
    webhook, or call an external create/cancel endpoint.
    """
    if not isinstance(operator_username, str) or not operator_username.strip() or len(operator_username) > 64:
        return {"status": "blocked", "reason": "An authenticated operator is required."}
    owner = uuid4().hex
    changed = db.query(RecoveryReservation).filter_by(payment_id=payment_id, state="needs_reconciliation").update(
        {"owner": owner, "state": "processing", "updated_at": datetime.utcnow()})
    db.commit()
    if not changed:
        return {"status": "blocked", "reason": "Case is active, already settled, or no longer awaiting reconciliation."}
    state = "needs_reconciliation"
    try:
        db.expire_all()
        evidence = check_reconciliation_status(db, payment_id, reference_key, supplied_provider_id)
        if evidence["result"] != "success":
            return {"status": "not_settled", "reason": "Provider has not verified full recovery. The case remains blocked."}
        payment, reference, provider_id = _reference(db, payment_id, reference_key, supplied_provider_id)
        execution = _bind_verified_intent(db, payment, reference, provider_id) if isinstance(reference, RecoveryIntent) else reference
        correlation = {"expected_order_id" if execution.provider_type == "order" else "expected_payment_link_id": provider_id}
        result = _observe_outcome(db, payment, **correlation, settle_only=True)
        if result["status"] != "recovered":
            db.rollback()
            return {"status": "not_settled", "reason": "Outcome requires manual investigation. The case remains blocked."}
        db.add(AuditLog(payment_id=payment_id, event_type="reconciliation_settled",
                        reason="Operator settled a verified provider success",
                        payload_json=json.dumps({"operator": operator_username, "execution_id": execution.id,
                                                 "provider_id": provider_id})))
        db.commit()
        state = None
        return {"status": "recovered", "execution_id": execution.id}
    except ReconciliationError as exc:
        db.rollback()
        return {"status": "not_settled", "reason": str(exc)}
    except Exception:
        db.rollback()
        return {"status": "not_settled", "reason": "Verification could not complete. The case remains blocked; no new payment action was requested."}
    finally:
        finish_recovery(db, payment_id, owner, state)


def return_verified_failure_to_review(db,payment_id,reference_key,operator_username):
    """Re-read all known attempts under a reconciliation claim; create a review only."""
    from app.config import settings
    from app.services.original_orders import original_order_eligibility,read_original_order
    from app.services.eligibility import is_recovery_eligible
    if (not settings.razorpay_key_id.startswith('rzp_test_') or not isinstance(operator_username,str)
            or not operator_username.strip() or len(operator_username)>64):
        return {'status':'blocked','reason':'Authenticated Test Mode operator required'}
    owner=uuid4().hex
    changed=db.query(RecoveryReservation).filter_by(payment_id=payment_id,state='needs_reconciliation').update(
        {'owner':owner,'state':'processing','updated_at':datetime.utcnow()})
    db.commit()
    if not changed:return {'status':'blocked','reason':'Case is active, already reviewed or not awaiting reconciliation'}
    next_state='needs_reconciliation'
    try:
        db.expire_all()
        payment,reference,provider_id=_reference(db,payment_id,reference_key)
        if not isinstance(reference,RecoveryExecution):
            raise ReconciliationError('Bind and verify uncertain creation intent before continuing')
        if not is_recovery_eligible(payment)[0] or not original_order_eligibility(db,payment)[0]:
            raise ReconciliationError('Case is stopped, closed or no longer eligible')
        if db.query(RecoveryIntent).filter(RecoveryIntent.payment_id==payment_id,
                RecoveryIntent.execution_id.is_(None),RecoveryIntent.state!='cancelled_before_creation').first():
            raise ReconciliationError('Unresolved creation intent requires investigation')
        executions=db.query(RecoveryExecution).filter_by(payment_id=payment_id).order_by(RecoveryExecution.id).all()
        if not executions or len(executions)>10 or executions[-1].id!=reference.id:
            raise ReconciliationError('Select the latest recorded execution; ambiguous history stays blocked')
        if payment.order_id and read_original_order(payment)['status']!='open':
            raise ReconciliationError('Original order is not verified open; no new recovery review')
        for execution in executions:
            evidence=check_reconciliation_status(db,payment_id,'execution:'+str(execution.id))
            if evidence['result']!='failed':
                raise ReconciliationError('Every existing execution must be verified failed; pending or paid resources stay blocked')
        correlation={'expected_order_id' if reference.provider_type=='order' else 'expected_payment_link_id':provider_id}
        result=_observe_outcome(db,payment,**correlation,settle_only=True,review_failed_only=True)
        if result.get('status')!='pending_review':
            return {'status':'blocked','reason':'Fresh provider evidence changed; investigate before continuing'}
        db.add(AuditLog(payment_id=payment_id,event_type='failed_execution_reviewed',
                        reason='Operator verified existing failures and returned the case to manual review; no provider creation',
                        payload_json=json.dumps({'operator':operator_username,'execution_id':reference.id})))
        db.commit();next_state='pending_review'
        return result
    except ReconciliationError as error:
        db.rollback();return {'status':'blocked','reason':str(error)}
    except Exception:
        db.rollback();return {'status':'blocked','reason':'Verification unavailable or changed; case remains blocked and no new payment was requested'}
    finally:
        finish_recovery(db,payment_id,owner,next_state)



def resume_unattempted_retry(db, payment_id, reference_key, operator_username):
    """Explicit review of one issued retry order; never recreate or charge anything."""
    from app.config import settings
    from app.models.models import Outcome
    from app.services.eligibility import is_recovery_eligible
    from app.services.original_orders import original_order_eligibility, read_original_order
    if (not settings.razorpay_key_id.startswith('rzp_test_') or not isinstance(operator_username, str)
            or not operator_username.strip() or len(operator_username) > 64):
        return {'status': 'blocked', 'reason': 'Authenticated Test Mode operator required'}
    owner = uuid4().hex
    changed = db.query(RecoveryReservation).filter_by(payment_id=payment_id, state='needs_reconciliation').update(
        {'owner': owner, 'state': 'processing', 'updated_at': datetime.utcnow()})
    db.commit()
    if not changed:
        return {'status': 'blocked', 'reason': 'Case is active or no longer awaiting reconciliation'}
    next_state = 'needs_reconciliation'
    try:
        db.expire_all()
        payment, reference, provider_id = _reference(db, payment_id, reference_key)
        executions = db.query(RecoveryExecution).filter_by(payment_id=payment_id).all()
        actions = db.query(Action).filter_by(payment_id=payment_id, decision_type=DecisionType.auto).all()
        if (not isinstance(reference, RecoveryExecution) or reference.provider_type != 'order'
                or len(executions) != 1 or executions[0].id != reference.id
                or len(actions) != 1 or actions[0].id != reference.action_id or actions[0].action_type != 'retry'):
            raise ReconciliationError('Only one exactly attributed first retry order can resume; ambiguous history stays blocked')
        if (not payment.order_id or not is_recovery_eligible(payment)[0]
                or not original_order_eligibility(db, payment)[0]):
            raise ReconciliationError('Case is stopped, closed or has no verified original order')
        if (db.query(Outcome).filter_by(payment_id=payment_id).first()
                or db.query(Action).filter_by(payment_id=payment_id, review_status='pending').first()
                or db.query(RecoveryIntent).filter(RecoveryIntent.payment_id == payment_id,
                    RecoveryIntent.execution_id.is_(None), RecoveryIntent.state != 'cancelled_before_creation').first()):
            raise ReconciliationError('Unresolved outcome, review or creation intent requires investigation')
        order = client.order.fetch(provider_id)
        if (not isinstance(order, dict) or order.get('id') != provider_id or order.get('status') != 'created'
                or type(order.get('amount')) is not int or order['amount'] != reference.amount_paise
                or order.get('currency') != reference.currency or reference.currency != 'INR'
                or type(order.get('amount_paid')) is not int or order['amount_paid'] != 0
                or type(order.get('amount_due')) is not int or order['amount_due'] != reference.amount_paise
                or type(order.get('attempts')) is not int or order['attempts'] != 0):
            raise ReconciliationError('Retry must be exactly matched, completely unpaid and never attempted')
        attempts = client.order.payments(provider_id)
        if (not isinstance(attempts, dict) or attempts.get('items') != []
                or type(attempts.get('items')) is not list
                or type(attempts.get('count', 0)) is not int or attempts.get('count', 0) != 0):
            raise ReconciliationError('Any payment attempt or inconsistent history prevents resumption')
        if read_original_order(payment)['status'] != 'open':
            raise ReconciliationError('Original order is not verified open')
        db.refresh(payment)
        if not is_recovery_eligible(payment)[0] or not original_order_eligibility(db, payment)[0]:
            raise ReconciliationError('Case eligibility changed during review')
        db.add(AuditLog(payment_id=payment_id, event_type='unattempted_retry_resumed',
            reason='Operator verified one unpaid, never-attempted retry and resumed observation; no provider creation',
            payload_json=json.dumps({'operator': operator_username, 'execution_id': reference.id, 'provider_id': provider_id})))
        next_state = 'awaiting_outcome'
        return {'status': 'awaiting_outcome', 'execution_id': reference.id, 'provider_id': provider_id}
    except ReconciliationError as error:
        db.rollback()
        return {'status': 'blocked', 'reason': str(error)}
    except Exception:
        db.rollback()
        return {'status': 'blocked', 'reason': 'Verification unavailable; case remains blocked and no payment request was sent'}
    finally:
        finish_recovery(db, payment_id, owner, next_state)
