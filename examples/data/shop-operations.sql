-- Fictional shop activity; every statement is parsed, never executed.
SELECT o.id, o.total_cents
FROM shop.orders AS o
WHERE o.status = 'pending'
ORDER BY o.id;

SELECT o.id, o.total_cents
FROM shop.orders AS o
WHERE o.status = 'pending'
ORDER BY o.id;

SELECT o.id, o.total_cents
FROM shop.orders AS o
WHERE o.status = 'pending'
ORDER BY o.id;

UPDATE shop.orders SET status = 'processing' WHERE id = 4101;
UPDATE shop.orders SET status = 'processing' WHERE id = 4102;

INSERT INTO shop.audit_events (order_id, action)
VALUES (4101, 'processing');
INSERT INTO shop.audit_events (order_id, action)
VALUES (4102, 'processing');

SELECT id, action
FROM shop.audit_events
WHERE order_id IN (4101, 4102)
ORDER BY id;

-- A semicolon inside a string is not a statement boundary.
INSERT INTO shop.audit_events (order_id, action)
VALUES (4103, 'review; manual');

WITH recent_orders AS (
    SELECT id, customer_id, total_cents
    FROM shop.orders
    WHERE status = 'processing'
)
SELECT r.id, c.name, r.total_cents
FROM recent_orders AS r
JOIN shop.customers AS c ON c.id = r.customer_id
ORDER BY r.id;

SELECT id, status FROM shop.orders WHERE id = 4101;
SELECT id, status FROM shop.orders WHERE id = 4102;

UPDATE shop.orders SET status = 'shipped' WHERE id = 4101;
UPDATE shop.orders SET status = 'shipped' WHERE id = 4102;
UPDATE shop.orders SET status = 'shipped' WHERE id = 4103;

INSERT INTO shop.audit_events (order_id, action)
VALUES (4101, 'shipped');
INSERT INTO shop.audit_events (order_id, action)
VALUES (4102, 'shipped');

SELECT id, action FROM shop.audit_events WHERE action = 'shipped';
SELECT id, action FROM shop.audit_events WHERE action = 'shipped';

DELETE FROM shop.audit_events WHERE order_id = 4099 AND action = 'duplicate';
DELETE FROM shop.audit_events WHERE order_id = 4098 AND action = 'duplicate';

SELECT id, total_cents FROM shop.orders WHERE status = 'shipped';
SELECT id, total_cents FROM shop.orders WHERE status = 'shipped';

UPDATE shop.customers SET tier = 'gold' WHERE id = 201;
SELECT id, name, tier FROM shop.customers WHERE id = 201;
