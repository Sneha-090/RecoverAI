"""Deterministic in-memory Razorpay substitute for offline demonstrations only."""

from copy import deepcopy
import time


class DemoProvider:
    def __init__(self):
        self.orders, self.links, self.payments = {}, {}, {}
        self.order_attempts = {}
        self.creations = 0
        self.captures = 0
        self.last_created = None
        self.lose_next_response = False
        self.on_create = None

    def failed_payment(self, payment_id, amount=499, reason='payment_declined'):
        entity = {'id': payment_id, 'amount': round(amount*100), 'currency':'INR',
                  'order_id':None, 'method':'card', 'status':'failed',
                  'error_code':'BAD_REQUEST_ERROR', 'error_reason':reason, 'created_at':int(time.time())}
        self.payments[payment_id] = entity
        return deepcopy(entity)

    def _create(self, kind, request):
        self.creations += 1
        identity = ('order_' if kind == 'order' else 'plink_') + f'Demo{self.creations:03d}'
        resource = {**deepcopy(request), 'id':identity, 'status':'created', 'amount_paid':0}
        if kind == 'payment_link':
            resource['short_url'] = f'https://example.invalid/offline/{identity}'
            self.links[identity] = resource
        else:
            self.orders[identity] = resource
            self.order_attempts[identity] = []
        self.last_created = (kind, identity)
        if self.on_create:
            callback, self.on_create = self.on_create, None
            callback(self.last_created)
        if self.lose_next_response:
            self.lose_next_response = False
            raise TimeoutError('Simulated response loss after provider accepted creation')
        return deepcopy(resource)

    def create_order(self, request):
        return self._create('order', request)

    def create_link(self, request):
        return self._create('payment_link', request)

    def fetch_order(self, identity):
        return deepcopy(self.orders[identity])

    def fetch_link(self, identity):
        return deepcopy(self.links[identity])

    def fetch_payment(self, identity):
        return deepcopy(self.payments[identity])

    def order_payments(self, identity):
        return {'items':deepcopy(self.order_attempts[identity])}

    def capture(self, reference):
        kind, identity = reference
        self.captures += 1
        resource = self.orders[identity] if kind == 'order' else self.links[identity]
        resource.update(status='paid', amount_paid=resource['amount'])
        entity = {'id':f'pay_DemoCapture{self.captures:03d}', 'status':'captured',
                  'amount':resource['amount'], 'currency':resource['currency'],
                  'order_id':identity if kind == 'order' else f'order_DemoLink{self.captures:03d}',
                  'description':None if kind == 'order' else '#'+identity.removeprefix('plink_')}
        methods = resource.get('options', {}).get('checkout', {}).get('method', {})
        entity['method'] = next((method for method, enabled in methods.items() if enabled), 'card')
        if kind == 'payment_link':
            resource['payments'] = [{'payment_id': entity['id']}]
        self.payments[entity['id']] = entity
        if kind == 'order':
            self.order_attempts[identity].append(deepcopy(entity))
        return deepcopy(entity)

    def fail_attempt(self, reference):
        kind, identity = reference
        if kind == 'order':
            self.order_attempts[identity].append({'id':'pay_DemoFailedAttempt', 'status':'failed'})
        else:
            self.links[identity]['status'] = 'expired'
