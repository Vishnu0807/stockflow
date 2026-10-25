"""Report SQL is explicit so its grouping rules can be inspected and discussed."""
from django.db import connection


def rows(sql):
    with connection.cursor() as cursor:
        cursor.execute(sql)
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]


def report_data():
    daily = rows('''
        SELECT CAST(o.created_at AS DATE) AS day, COUNT(DISTINCT o.id) AS orders,
               SUM(i.quantity * i.unit_price) AS value
        FROM shop_order o JOIN shop_orderitem i ON i.order_id = o.id
        WHERE o.status = 'completed'
        GROUP BY CAST(o.created_at AS DATE) ORDER BY day DESC LIMIT 30
    ''')
    top = rows('''
        SELECT p.sku, p.name, SUM(i.quantity) AS units,
               SUM(i.quantity * i.unit_price) AS value
        FROM shop_orderitem i JOIN shop_order o ON o.id = i.order_id
        JOIN shop_product p ON p.id = i.product_id
        WHERE o.status = 'completed'
        GROUP BY p.id, p.sku, p.name ORDER BY units DESC, p.sku LIMIT 10
    ''')
    summary = rows('''
        SELECT COUNT(*) AS total,
               COALESCE(SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END), 0) AS cancelled,
               COALESCE(SUM(CASE WHEN status = 'returned' THEN 1 ELSE 0 END), 0) AS returned
        FROM shop_order
    ''')[0]
    summary['cancellation_rate'] = 100 * summary['cancelled'] / max(summary['total'], 1)
    summary['value'] = rows('''
        SELECT COALESCE(SUM(i.quantity * i.unit_price), 0) AS value
        FROM shop_orderitem i JOIN shop_order o ON o.id = i.order_id
        WHERE o.status = 'completed'
    ''')[0]['value']
    return {'daily': daily, 'top': top, 'summary': summary}
