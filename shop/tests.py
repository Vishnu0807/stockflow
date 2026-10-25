import threading
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from rest_framework.test import APIClient

from .models import Order, OrderItem, Product, StockEvent
from .reports import report_data
from .services import StockError, add_product, adjust_stock, change_status, place_order


def product(sku='P1', count=4, price='10.00'):
    return add_product({'sku': sku, 'name': 'Notebook', 'price': Decimal(price),
                        'on_hand': count, 'reorder_point': 1}, 'test')


class StockTests(TestCase):
    def setUp(self):
        self.p = product()

    def test_reserve_complete_return_and_snapshot_price(self):
        order, created = place_order('Alex', [(self.p.pk, 2)], uuid.uuid4(), 'test')
        self.assertTrue(created)
        self.p.refresh_from_db()
        self.assertEqual((self.p.on_hand, self.p.reserved, self.p.available), (4, 2, 2))
        self.assertEqual(order.total, Decimal('20.00'))
        self.p.price = Decimal('99.00')
        self.p.save(update_fields=['price'])
        self.assertEqual(OrderItem.objects.get(order=order).unit_price, Decimal('10.00'))
        change_status(order.pk, 'completed', 'test')
        self.p.refresh_from_db()
        self.assertEqual((self.p.on_hand, self.p.reserved), (2, 0))
        self.assertEqual(report_data()['summary']['value'], Decimal('20.00'))
        change_status(order.pk, 'returned', 'test')
        change_status(order.pk, 'returned', 'test')
        self.p.refresh_from_db()
        self.assertEqual((self.p.on_hand, self.p.reserved), (4, 0))
        self.assertEqual(report_data()['summary']['value'], 0)
        self.assertEqual(StockEvent.objects.filter(order=order, kind='returned').count(), 1)

    def test_cancel_twice_only_releases_once(self):
        order, _ = place_order('Alex', [(self.p.pk, 3)], uuid.uuid4(), 'test')
        change_status(order.pk, 'cancelled', 'test')
        change_status(order.pk, 'cancelled', 'test')
        self.p.refresh_from_db()
        self.assertEqual((self.p.on_hand, self.p.reserved), (4, 0))
        self.assertEqual(StockEvent.objects.filter(order=order, kind='cancelled').count(), 1)

    def test_idempotency_checks_payload_and_order_limit(self):
        key = uuid.uuid4()
        first, created = place_order('Alex', [(self.p.pk, 2)], key, 'test')
        again, created_again = place_order('Alex', [(self.p.pk, 2)], key, 'test')
        self.assertEqual(first.pk, again.pk)
        self.assertFalse(created_again)
        with self.assertRaises(StockError):
            place_order('Alex', [(self.p.pk, 1)], key, 'test')
        with self.assertRaises(StockError):
            place_order('Other', [(self.p.pk, 3)], uuid.uuid4(), 'test')
        self.assertEqual(Order.objects.count(), 1)

    def test_multi_item_failure_rolls_back_order_and_first_reservation(self):
        second = product('P2', count=1)
        with self.assertRaises(StockError):
            place_order('Alex', [(self.p.pk, 2), (second.pk, 2)], uuid.uuid4(), 'test')
        self.p.refresh_from_db()
        self.assertEqual(self.p.reserved, 0)
        self.assertEqual(Order.objects.count(), 0)
        self.assertFalse(StockEvent.objects.filter(kind='reservation').exists())

    def test_adjustment_cannot_remove_reserved_stock(self):
        place_order('Alex', [(self.p.pk, 3)], uuid.uuid4(), 'test')
        with self.assertRaises(StockError):
            adjust_stock(self.p.pk, -2, 'Damaged', 'test')
        self.p.refresh_from_db()
        self.assertEqual((self.p.on_hand, self.p.reserved), (4, 3))

    def test_read_only_pages_and_authenticated_writes(self):
        self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.get('/orders/').status_code, 200)
        self.assertEqual(self.client.get('/reports/').status_code, 200)
        self.assertEqual(self.client.get('/orders/new/').status_code, 302)
        user = get_user_model().objects.create_user('operator', password='test-password')
        self.client.force_login(user)
        page = self.client.get('/orders/new/')
        self.assertContains(page, 'Reserve stock')
        self.assertEqual(self.client.post('/orders/new/', {'customer': 'Walk-in',
            'request_key': str(uuid.uuid4()), f'qty_{self.p.pk}': '2'}).status_code, 302)
        self.assertContains(self.client.get('/orders/'), 'Walk-in')

    def test_api_validation_and_duplicate_response(self):
        api = APIClient()
        key = str(uuid.uuid4())
        data = {'customer': 'Alex', 'request_key': key, 'items': [{'product_id': self.p.pk, 'quantity': 2}]}
        self.assertEqual(api.post('/api/orders/', data, format='json').status_code, 403)
        user = get_user_model().objects.create_user('operator', password='test-password')
        api.force_authenticate(user)
        self.assertEqual(api.post('/api/orders/', data, format='json').status_code, 201)
        self.assertEqual(api.post('/api/orders/', data, format='json').status_code, 200)
        data['items'][0]['quantity'] = 3
        self.assertEqual(api.post('/api/orders/', data, format='json').status_code, 409)
        self.assertEqual(api.post('/api/orders/', {'items': []}, format='json').status_code, 400)


class PostgreSQLConcurrencyTests(TransactionTestCase):
    def test_two_orders_for_last_unit(self):
        if connection.vendor != 'postgresql':
            self.skipTest('Row-lock concurrency behavior requires PostgreSQL.')
        p = product(count=1)
        barrier = threading.Barrier(2)
        outcomes = []

        def worker(number):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                place_order(f'Buyer {number}', [(p.pk, 1)], uuid.uuid4(), 'test')
                outcomes.append('success')
            except StockError:
                outcomes.append('out-of-stock')
            finally:
                close_old_connections()

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        self.assertFalse(any(t.is_alive() for t in threads))
        self.assertCountEqual(outcomes, ['success', 'out-of-stock'])
        p.refresh_from_db()
        self.assertEqual((p.on_hand, p.reserved), (1, 1))
        self.assertEqual(Order.objects.count(), 1)
