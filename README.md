# StockFlow

StockFlow is a small inventory and order application. An operator can add products, adjust stock, reserve an order, fulfil it, cancel it, or record a full return. Anyone can inspect the demo's inventory, orders, and reports; changes require an operator login.

The interesting problem is keeping stock correct when requests repeat or overlap. A product tracks physical units (`on_hand`) and units promised to unfulfilled orders (`reserved`). Available stock is `on_hand - reserved`.

| Action | On hand | Reserved |
| --- | ---: | ---: |
| Receive 5 units | +5 | 0 |
| Reserve 2 units | 0 | +2 |
| Complete that order | −2 | −2 |
| Cancel before completing | 0 | −2 |
| Return a completed order | +2 | 0 |

Status transitions only allow `reserved → completed`, `reserved → cancelled`, and `completed → returned`. A repeated transition has no additional effect. The demo does not process payments or partial returns.

## Run locally (Windows PowerShell)

Install Python 3.12, extract this project, and open PowerShell in the folder containing `manage.py`:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py seed_demo
.\.venv\Scripts\python.exe manage.py createsuperuser
.\.venv\Scripts\python.exe manage.py runserver
```

Open <http://127.0.0.1:8000>. Sign in with the username and password you created to add orders or change stock. `seed_demo` adds six sample products and is safe to rerun. By default this quick preview uses a local SQLite file; it can demonstrate the workflow but **SQLite does not provide the PostgreSQL row locks used to protect concurrent orders**.

If `py -3.12` isn't found, install Python 3.12 and reopen PowerShell. To stop the server, press Ctrl+C. For future runs, only the final `runserver` command is needed.

## Run with PostgreSQL

If you have Docker Desktop, from this folder:

```powershell
docker compose up --build -d
docker compose exec web python manage.py createsuperuser
```

Open <http://127.0.0.1:8000>. Container startup applies migrations and adds missing sample products. `docker compose down` stops the containers without deleting the database volume. In this configuration PostgreSQL stores orders, audit events, and stock; the named volume keeps them between restarts. The Compose password and key are for **local development only**. Use private credentials and `DEBUG=0` on an actual host.

To run the concurrency test against that PostgreSQL container with your local Python environment, expose the database port or use `docker compose exec web` after installing the dev requirements there. The GitHub Actions workflow already starts PostgreSQL and runs that test on every push.

## What to try

1. Open **Inventory**. Notice that the sample tote bag is below its low-stock threshold.
2. Sign in and create an order for two notebooks. `reserved` increases by two; `on_hand` remains unchanged.
3. Open the order and select **Mark completed**. Both figures decrease by two.
4. Open **Reports** to see the value of completed orders and the latest stock events.
5. Return the order. Physical units are restored, and completed order value is reduced accordingly.

The **Cancel order** option is only available before completion and releases its reservation. Every stock change writes a `StockEvent` with an operator and reason. There are no hidden automatic restocks.

## API

The same service functions power the UI and these endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/products/` | Public product list |
| POST | `/api/orders/` | Create or retry an order; operator login required |
| GET | `/api/orders/<id>/` | Public order detail in this sample demo |
| POST | `/api/orders/<id>/` | Update status; operator login required |

Write endpoints use Django's session authentication and CSRF protection. Log in through the website first, or use the browsable API after signing in. Example JSON for `POST /api/orders/`:

```json
{
  "customer": "Walk-in 012",
  "request_key": "15d56de2-d882-44bb-a7f8-578e32867e9c",
  "items": [{"product_id": 1, "quantity": 2}]
}
```

The request key is a client-generated UUID. The first valid request creates an order (HTTP 201). A retry with the same customer and items returns the existing order (HTTP 200); reusing the key with a different basket returns HTTP 409. Status updates take JSON such as `{"target":"completed"}`. Validation errors are HTTP 400; stock or transition conflicts are HTTP 409. A product's `price` is captured on each order item, so later price edits do not change old totals.

## Why the stock rules hold

`shop/services.py` wraps each stock operation in a database transaction. With PostgreSQL, `select_for_update()` locks product rows while an order checks availability and reserves units. Both the order and all its stock events commit together; an invalid item rolls everything back. Product rows are locked in ID order to reduce deadlocks. The database also enforces `reserved <= on_hand` and uniqueness of each request key. No stock change happens through a plain model save in the UI or API.

`shop/reports.py` uses explicit SQL joins and aggregation for daily completed order value and best-selling products. Daily values group by the order's creation date in the database; this is an operational report, not accounting revenue. The cancellation rate is cancelled orders divided by all orders ever placed. It can be explained without a graph or a model.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe manage.py check
```

The tests cover reservation, fulfilment, cancellation, full returns, price snapshots, duplicate requests, rollback after a multi-product failure, stock adjustments, authenticated UI/API writes, and API validation. A separate test races two orders for the last unit; it is skipped on SQLite and runs with PostgreSQL in GitHub Actions. Do not describe that race test as locally verified until you run it with PostgreSQL.

## Layout

```text
config/         Django settings and URL routes
shop/models.py  Products, orders, lines, and immutable stock events
shop/services.py Transactional inventory rules
shop/reports.py SQL reports
shop/api.py      Small REST interface using the same rules
shop/views.py    Three-page UI and operator forms
templates/       Server-rendered HTML
static/          One CSS file; no frontend build process
```
