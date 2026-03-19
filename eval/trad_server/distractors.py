"""Cross-domain distractor tools for scaling experiments.

Plausible tool definitions from 6 unrelated domains (calendar, inventory,
billing, HR/payroll, CI/CD, docs/wiki). None have backend implementations —
calling them triggers a DomainError in _dispatch().

Deterministic: same count always produces same tool set.
"""

from __future__ import annotations

# ── Domain pools ─────────────────────────────────────────────────────────────
# Each tool follows the same dict format as tools_15.py: name, description,
# parameters, required.

_CALENDAR = [
    {"name": "create_calendar_event", "description": "Create a new calendar event with title, start/end time, and optional attendees.", "parameters": {"title": {"type": "string"}, "start_time": {"type": "string", "description": "ISO 8601"}, "end_time": {"type": "string", "description": "ISO 8601"}, "attendee_ids": {"type": "array", "items": {"type": "string"}}}, "required": ["title", "start_time", "end_time"]},
    {"name": "update_calendar_event", "description": "Update an existing calendar event's time, title, or attendees.", "parameters": {"event_id": {"type": "string"}, "title": {"type": "string"}, "start_time": {"type": "string"}, "end_time": {"type": "string"}}, "required": ["event_id"]},
    {"name": "delete_calendar_event", "description": "Delete a calendar event by ID.", "parameters": {"event_id": {"type": "string"}}, "required": ["event_id"]},
    {"name": "get_calendar_event", "description": "Retrieve details of a calendar event by ID.", "parameters": {"event_id": {"type": "string"}}, "required": ["event_id"]},
    {"name": "list_calendar_events", "description": "List calendar events in a date range.", "parameters": {"start_date": {"type": "string"}, "end_date": {"type": "string"}, "calendar_id": {"type": "string"}}, "required": ["start_date", "end_date"]},
    {"name": "create_recurring_event", "description": "Create a recurring calendar event with a recurrence rule.", "parameters": {"title": {"type": "string"}, "start_time": {"type": "string"}, "end_time": {"type": "string"}, "recurrence": {"type": "string", "description": "RRULE string"}}, "required": ["title", "start_time", "end_time", "recurrence"]},
    {"name": "accept_invitation", "description": "Accept a calendar event invitation.", "parameters": {"event_id": {"type": "string"}}, "required": ["event_id"]},
    {"name": "decline_invitation", "description": "Decline a calendar event invitation.", "parameters": {"event_id": {"type": "string"}}, "required": ["event_id"]},
    {"name": "propose_new_time", "description": "Propose an alternative time for a calendar event.", "parameters": {"event_id": {"type": "string"}, "new_start": {"type": "string"}, "new_end": {"type": "string"}}, "required": ["event_id", "new_start", "new_end"]},
    {"name": "check_availability", "description": "Check a user's availability for a time range.", "parameters": {"user_id": {"type": "string"}, "start_time": {"type": "string"}, "end_time": {"type": "string"}}, "required": ["user_id", "start_time", "end_time"]},
    {"name": "book_room", "description": "Book a meeting room for a time slot.", "parameters": {"room_id": {"type": "string"}, "start_time": {"type": "string"}, "end_time": {"type": "string"}, "event_id": {"type": "string"}}, "required": ["room_id", "start_time", "end_time"]},
    {"name": "cancel_room_booking", "description": "Cancel an existing room booking.", "parameters": {"booking_id": {"type": "string"}}, "required": ["booking_id"]},
    {"name": "list_rooms", "description": "List available meeting rooms, optionally filtered by capacity.", "parameters": {"min_capacity": {"type": "integer"}, "floor": {"type": "string"}}, "required": []},
    {"name": "get_room_schedule", "description": "Get the schedule for a meeting room on a given date.", "parameters": {"room_id": {"type": "string"}, "date": {"type": "string"}}, "required": ["room_id", "date"]},
    {"name": "set_working_hours", "description": "Set a user's working hours for scheduling.", "parameters": {"user_id": {"type": "string"}, "start_hour": {"type": "integer"}, "end_hour": {"type": "integer"}, "timezone": {"type": "string"}}, "required": ["user_id", "start_hour", "end_hour"]},
    {"name": "get_working_hours", "description": "Get a user's configured working hours.", "parameters": {"user_id": {"type": "string"}}, "required": ["user_id"]},
    {"name": "create_calendar", "description": "Create a new shared calendar.", "parameters": {"name": {"type": "string"}, "description": {"type": "string"}}, "required": ["name"]},
    {"name": "share_calendar", "description": "Share a calendar with another user.", "parameters": {"calendar_id": {"type": "string"}, "user_id": {"type": "string"}, "permission": {"type": "string", "enum": ["read", "write", "admin"]}}, "required": ["calendar_id", "user_id"]},
    {"name": "set_event_reminder", "description": "Set a reminder for a calendar event.", "parameters": {"event_id": {"type": "string"}, "minutes_before": {"type": "integer"}}, "required": ["event_id", "minutes_before"]},
    {"name": "get_daily_agenda", "description": "Get a user's agenda for a specific date.", "parameters": {"user_id": {"type": "string"}, "date": {"type": "string"}}, "required": ["user_id", "date"]},
]

_INVENTORY = [
    {"name": "create_product", "description": "Create a new product in the catalog with name, SKU, and price.", "parameters": {"name": {"type": "string"}, "sku": {"type": "string"}, "price": {"type": "number"}, "category": {"type": "string"}}, "required": ["name", "sku", "price"]},
    {"name": "update_product", "description": "Update product details like name, price, or category.", "parameters": {"product_id": {"type": "string"}, "name": {"type": "string"}, "price": {"type": "number"}, "category": {"type": "string"}}, "required": ["product_id"]},
    {"name": "get_product", "description": "Retrieve product details by ID.", "parameters": {"product_id": {"type": "string"}}, "required": ["product_id"]},
    {"name": "search_products", "description": "Search products by name, category, or price range.", "parameters": {"query": {"type": "string"}, "category": {"type": "string"}, "min_price": {"type": "number"}, "max_price": {"type": "number"}}, "required": []},
    {"name": "adjust_stock", "description": "Adjust stock quantity for a product in a warehouse.", "parameters": {"product_id": {"type": "string"}, "warehouse_id": {"type": "string"}, "quantity_delta": {"type": "integer"}}, "required": ["product_id", "warehouse_id", "quantity_delta"]},
    {"name": "create_warehouse", "description": "Create a new warehouse location.", "parameters": {"name": {"type": "string"}, "address": {"type": "string"}, "capacity": {"type": "integer"}}, "required": ["name", "address"]},
    {"name": "get_warehouse", "description": "Get warehouse details by ID.", "parameters": {"warehouse_id": {"type": "string"}}, "required": ["warehouse_id"]},
    {"name": "transfer_stock", "description": "Transfer stock between warehouses.", "parameters": {"product_id": {"type": "string"}, "from_warehouse": {"type": "string"}, "to_warehouse": {"type": "string"}, "quantity": {"type": "integer"}}, "required": ["product_id", "from_warehouse", "to_warehouse", "quantity"]},
    {"name": "create_purchase_order", "description": "Create a purchase order for restocking.", "parameters": {"supplier_id": {"type": "string"}, "items": {"type": "array", "items": {"type": "object"}}, "warehouse_id": {"type": "string"}}, "required": ["supplier_id", "items"]},
    {"name": "approve_purchase_order", "description": "Approve a pending purchase order.", "parameters": {"order_id": {"type": "string"}}, "required": ["order_id"]},
    {"name": "receive_shipment", "description": "Record receipt of a shipment against a purchase order.", "parameters": {"order_id": {"type": "string"}, "received_items": {"type": "array", "items": {"type": "object"}}}, "required": ["order_id", "received_items"]},
    {"name": "create_inventory_count", "description": "Initiate a physical inventory count for a warehouse.", "parameters": {"warehouse_id": {"type": "string"}, "count_date": {"type": "string"}}, "required": ["warehouse_id"]},
    {"name": "get_stock_level", "description": "Get current stock level for a product across warehouses.", "parameters": {"product_id": {"type": "string"}, "warehouse_id": {"type": "string"}}, "required": ["product_id"]},
    {"name": "set_reorder_point", "description": "Set the automatic reorder point for a product.", "parameters": {"product_id": {"type": "string"}, "reorder_point": {"type": "integer"}, "reorder_quantity": {"type": "integer"}}, "required": ["product_id", "reorder_point"]},
    {"name": "list_warehouses", "description": "List all warehouses.", "parameters": {}, "required": []},
    {"name": "get_product_history", "description": "Get stock movement history for a product.", "parameters": {"product_id": {"type": "string"}, "start_date": {"type": "string"}, "end_date": {"type": "string"}}, "required": ["product_id"]},
    {"name": "create_supplier", "description": "Register a new supplier.", "parameters": {"name": {"type": "string"}, "contact_email": {"type": "string"}, "phone": {"type": "string"}}, "required": ["name", "contact_email"]},
    {"name": "get_supplier", "description": "Get supplier details by ID.", "parameters": {"supplier_id": {"type": "string"}}, "required": ["supplier_id"]},
    {"name": "archive_product", "description": "Archive a discontinued product.", "parameters": {"product_id": {"type": "string"}}, "required": ["product_id"]},
    {"name": "bulk_stock_update", "description": "Update stock levels for multiple products at once.", "parameters": {"updates": {"type": "array", "items": {"type": "object"}}, "warehouse_id": {"type": "string"}}, "required": ["updates", "warehouse_id"]},
]

_BILLING = [
    {"name": "create_invoice", "description": "Create a new invoice for a customer.", "parameters": {"customer_id": {"type": "string"}, "line_items": {"type": "array", "items": {"type": "object"}}, "due_date": {"type": "string"}}, "required": ["customer_id", "line_items"]},
    {"name": "send_invoice", "description": "Send an invoice to the customer via email.", "parameters": {"invoice_id": {"type": "string"}}, "required": ["invoice_id"]},
    {"name": "void_invoice", "description": "Void an unpaid invoice.", "parameters": {"invoice_id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["invoice_id"]},
    {"name": "get_invoice", "description": "Retrieve invoice details by ID.", "parameters": {"invoice_id": {"type": "string"}}, "required": ["invoice_id"]},
    {"name": "list_invoices", "description": "List invoices filtered by status or customer.", "parameters": {"customer_id": {"type": "string"}, "status": {"type": "string", "enum": ["draft", "sent", "paid", "overdue", "void"]}}, "required": []},
    {"name": "record_payment", "description": "Record a payment against an invoice.", "parameters": {"invoice_id": {"type": "string"}, "amount": {"type": "number"}, "payment_method": {"type": "string"}}, "required": ["invoice_id", "amount"]},
    {"name": "create_credit_note", "description": "Issue a credit note against an invoice.", "parameters": {"invoice_id": {"type": "string"}, "amount": {"type": "number"}, "reason": {"type": "string"}}, "required": ["invoice_id", "amount"]},
    {"name": "get_payment_history", "description": "Get payment history for a customer.", "parameters": {"customer_id": {"type": "string"}, "start_date": {"type": "string"}, "end_date": {"type": "string"}}, "required": ["customer_id"]},
    {"name": "create_subscription", "description": "Create a recurring subscription for a customer.", "parameters": {"customer_id": {"type": "string"}, "plan_id": {"type": "string"}, "start_date": {"type": "string"}}, "required": ["customer_id", "plan_id"]},
    {"name": "cancel_subscription", "description": "Cancel an active subscription.", "parameters": {"subscription_id": {"type": "string"}, "cancel_at_period_end": {"type": "boolean"}}, "required": ["subscription_id"]},
    {"name": "update_subscription", "description": "Change a subscription's plan or billing cycle.", "parameters": {"subscription_id": {"type": "string"}, "plan_id": {"type": "string"}}, "required": ["subscription_id"]},
    {"name": "get_subscription", "description": "Get subscription details by ID.", "parameters": {"subscription_id": {"type": "string"}}, "required": ["subscription_id"]},
    {"name": "create_tax_rate", "description": "Create a tax rate for invoicing.", "parameters": {"name": {"type": "string"}, "percentage": {"type": "number"}, "region": {"type": "string"}}, "required": ["name", "percentage"]},
    {"name": "apply_discount", "description": "Apply a discount code to an invoice.", "parameters": {"invoice_id": {"type": "string"}, "discount_code": {"type": "string"}}, "required": ["invoice_id", "discount_code"]},
    {"name": "generate_statement", "description": "Generate an account statement for a customer.", "parameters": {"customer_id": {"type": "string"}, "start_date": {"type": "string"}, "end_date": {"type": "string"}}, "required": ["customer_id"]},
    {"name": "get_account_balance", "description": "Get the outstanding balance for a customer.", "parameters": {"customer_id": {"type": "string"}}, "required": ["customer_id"]},
    {"name": "create_customer", "description": "Create a new billing customer.", "parameters": {"name": {"type": "string"}, "email": {"type": "string"}, "billing_address": {"type": "string"}}, "required": ["name", "email"]},
    {"name": "update_billing_address", "description": "Update a customer's billing address.", "parameters": {"customer_id": {"type": "string"}, "billing_address": {"type": "string"}}, "required": ["customer_id", "billing_address"]},
    {"name": "export_transactions", "description": "Export transactions to CSV for a date range.", "parameters": {"start_date": {"type": "string"}, "end_date": {"type": "string"}, "format": {"type": "string", "enum": ["csv", "json"]}}, "required": ["start_date", "end_date"]},
    {"name": "reconcile_payments", "description": "Run payment reconciliation for a period.", "parameters": {"start_date": {"type": "string"}, "end_date": {"type": "string"}}, "required": ["start_date", "end_date"]},
]

_HR = [
    {"name": "create_employee", "description": "Create a new employee record.", "parameters": {"name": {"type": "string"}, "email": {"type": "string"}, "department_id": {"type": "string"}, "role": {"type": "string"}, "start_date": {"type": "string"}}, "required": ["name", "email", "department_id"]},
    {"name": "update_employee", "description": "Update an employee's details.", "parameters": {"employee_id": {"type": "string"}, "name": {"type": "string"}, "department_id": {"type": "string"}, "role": {"type": "string"}}, "required": ["employee_id"]},
    {"name": "get_employee", "description": "Get employee details by ID.", "parameters": {"employee_id": {"type": "string"}}, "required": ["employee_id"]},
    {"name": "terminate_employee", "description": "Terminate an employee's record with an effective date.", "parameters": {"employee_id": {"type": "string"}, "effective_date": {"type": "string"}, "reason": {"type": "string"}}, "required": ["employee_id", "effective_date"]},
    {"name": "submit_timesheet", "description": "Submit a timesheet for a pay period.", "parameters": {"employee_id": {"type": "string"}, "period_start": {"type": "string"}, "period_end": {"type": "string"}, "hours": {"type": "number"}}, "required": ["employee_id", "period_start", "period_end", "hours"]},
    {"name": "approve_timesheet", "description": "Approve a submitted timesheet.", "parameters": {"timesheet_id": {"type": "string"}}, "required": ["timesheet_id"]},
    {"name": "request_leave", "description": "Submit a leave request.", "parameters": {"employee_id": {"type": "string"}, "leave_type": {"type": "string", "enum": ["vacation", "sick", "personal", "parental"]}, "start_date": {"type": "string"}, "end_date": {"type": "string"}}, "required": ["employee_id", "leave_type", "start_date", "end_date"]},
    {"name": "approve_leave", "description": "Approve a pending leave request.", "parameters": {"leave_id": {"type": "string"}}, "required": ["leave_id"]},
    {"name": "deny_leave", "description": "Deny a pending leave request with a reason.", "parameters": {"leave_id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["leave_id"]},
    {"name": "get_leave_balance", "description": "Get remaining leave balances for an employee.", "parameters": {"employee_id": {"type": "string"}}, "required": ["employee_id"]},
    {"name": "create_pay_run", "description": "Create a new payroll run for a period.", "parameters": {"period_start": {"type": "string"}, "period_end": {"type": "string"}, "department_id": {"type": "string"}}, "required": ["period_start", "period_end"]},
    {"name": "process_payroll", "description": "Process and finalize a payroll run.", "parameters": {"pay_run_id": {"type": "string"}}, "required": ["pay_run_id"]},
    {"name": "get_payslip", "description": "Get a payslip for an employee and pay period.", "parameters": {"employee_id": {"type": "string"}, "pay_run_id": {"type": "string"}}, "required": ["employee_id", "pay_run_id"]},
    {"name": "create_benefit_plan", "description": "Create a new employee benefit plan.", "parameters": {"name": {"type": "string"}, "type": {"type": "string", "enum": ["health", "dental", "vision", "retirement"]}, "monthly_cost": {"type": "number"}}, "required": ["name", "type"]},
    {"name": "enroll_in_benefit", "description": "Enroll an employee in a benefit plan.", "parameters": {"employee_id": {"type": "string"}, "plan_id": {"type": "string"}}, "required": ["employee_id", "plan_id"]},
    {"name": "create_department", "description": "Create a new department.", "parameters": {"name": {"type": "string"}, "parent_id": {"type": "string"}, "manager_id": {"type": "string"}}, "required": ["name"]},
    {"name": "transfer_employee", "description": "Transfer an employee to a different department.", "parameters": {"employee_id": {"type": "string"}, "new_department_id": {"type": "string"}, "effective_date": {"type": "string"}}, "required": ["employee_id", "new_department_id"]},
    {"name": "update_salary", "description": "Update an employee's salary.", "parameters": {"employee_id": {"type": "string"}, "new_salary": {"type": "number"}, "effective_date": {"type": "string"}, "reason": {"type": "string"}}, "required": ["employee_id", "new_salary"]},
    {"name": "get_org_chart", "description": "Get the organizational chart for a department.", "parameters": {"department_id": {"type": "string"}}, "required": ["department_id"]},
    {"name": "create_performance_review", "description": "Create a performance review for an employee.", "parameters": {"employee_id": {"type": "string"}, "reviewer_id": {"type": "string"}, "period": {"type": "string"}, "rating": {"type": "integer"}}, "required": ["employee_id", "reviewer_id", "period"]},
]

_CICD = [
    {"name": "trigger_build", "description": "Trigger a CI build for a branch or commit.", "parameters": {"pipeline_id": {"type": "string"}, "branch": {"type": "string"}, "commit_sha": {"type": "string"}}, "required": ["pipeline_id"]},
    {"name": "cancel_build", "description": "Cancel a running build.", "parameters": {"build_id": {"type": "string"}}, "required": ["build_id"]},
    {"name": "get_build_status", "description": "Get the status of a build.", "parameters": {"build_id": {"type": "string"}}, "required": ["build_id"]},
    {"name": "list_builds", "description": "List recent builds for a pipeline.", "parameters": {"pipeline_id": {"type": "string"}, "status": {"type": "string", "enum": ["pending", "running", "success", "failed", "cancelled"]}, "limit": {"type": "integer"}}, "required": ["pipeline_id"]},
    {"name": "create_pipeline", "description": "Create a new CI/CD pipeline.", "parameters": {"name": {"type": "string"}, "repository_url": {"type": "string"}, "config": {"type": "string"}}, "required": ["name", "repository_url"]},
    {"name": "update_pipeline", "description": "Update pipeline configuration.", "parameters": {"pipeline_id": {"type": "string"}, "config": {"type": "string"}, "name": {"type": "string"}}, "required": ["pipeline_id"]},
    {"name": "delete_pipeline", "description": "Delete a CI/CD pipeline.", "parameters": {"pipeline_id": {"type": "string"}}, "required": ["pipeline_id"]},
    {"name": "get_pipeline", "description": "Get pipeline details by ID.", "parameters": {"pipeline_id": {"type": "string"}}, "required": ["pipeline_id"]},
    {"name": "create_deployment", "description": "Create a deployment to an environment.", "parameters": {"pipeline_id": {"type": "string"}, "environment_id": {"type": "string"}, "build_id": {"type": "string"}}, "required": ["pipeline_id", "environment_id", "build_id"]},
    {"name": "rollback_deployment", "description": "Roll back to a previous deployment.", "parameters": {"deployment_id": {"type": "string"}, "target_version": {"type": "string"}}, "required": ["deployment_id"]},
    {"name": "get_deployment_status", "description": "Get the status of a deployment.", "parameters": {"deployment_id": {"type": "string"}}, "required": ["deployment_id"]},
    {"name": "list_deployments", "description": "List deployments for an environment.", "parameters": {"environment_id": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["environment_id"]},
    {"name": "create_environment", "description": "Create a deployment environment (staging, production, etc.).", "parameters": {"name": {"type": "string"}, "type": {"type": "string", "enum": ["development", "staging", "production"]}}, "required": ["name", "type"]},
    {"name": "get_environment", "description": "Get environment details by ID.", "parameters": {"environment_id": {"type": "string"}}, "required": ["environment_id"]},
    {"name": "set_environment_variable", "description": "Set an environment variable for a deployment environment.", "parameters": {"environment_id": {"type": "string"}, "key": {"type": "string"}, "value": {"type": "string"}, "is_secret": {"type": "boolean"}}, "required": ["environment_id", "key", "value"]},
    {"name": "get_build_logs", "description": "Retrieve logs for a build.", "parameters": {"build_id": {"type": "string"}, "step": {"type": "string"}}, "required": ["build_id"]},
    {"name": "approve_deployment", "description": "Approve a deployment that requires manual approval.", "parameters": {"deployment_id": {"type": "string"}}, "required": ["deployment_id"]},
    {"name": "create_release", "description": "Create a versioned release.", "parameters": {"pipeline_id": {"type": "string"}, "version": {"type": "string"}, "notes": {"type": "string"}}, "required": ["pipeline_id", "version"]},
    {"name": "tag_release", "description": "Tag a release with metadata.", "parameters": {"release_id": {"type": "string"}, "tag": {"type": "string"}}, "required": ["release_id", "tag"]},
    {"name": "get_artifact", "description": "Download a build artifact.", "parameters": {"build_id": {"type": "string"}, "artifact_name": {"type": "string"}}, "required": ["build_id", "artifact_name"]},
]

_DOCS = [
    {"name": "create_page", "description": "Create a new wiki page.", "parameters": {"space_id": {"type": "string"}, "title": {"type": "string"}, "body": {"type": "string"}, "parent_page_id": {"type": "string"}}, "required": ["space_id", "title", "body"]},
    {"name": "update_page", "description": "Update a wiki page's content.", "parameters": {"page_id": {"type": "string"}, "title": {"type": "string"}, "body": {"type": "string"}}, "required": ["page_id"]},
    {"name": "delete_page", "description": "Delete a wiki page.", "parameters": {"page_id": {"type": "string"}}, "required": ["page_id"]},
    {"name": "get_page", "description": "Get a wiki page by ID.", "parameters": {"page_id": {"type": "string"}}, "required": ["page_id"]},
    {"name": "search_pages", "description": "Search wiki pages by keyword.", "parameters": {"query": {"type": "string"}, "space_id": {"type": "string"}}, "required": ["query"]},
    {"name": "create_space", "description": "Create a new wiki space.", "parameters": {"name": {"type": "string"}, "description": {"type": "string"}, "visibility": {"type": "string", "enum": ["public", "private"]}}, "required": ["name"]},
    {"name": "archive_space", "description": "Archive a wiki space.", "parameters": {"space_id": {"type": "string"}}, "required": ["space_id"]},
    {"name": "get_space", "description": "Get wiki space details by ID.", "parameters": {"space_id": {"type": "string"}}, "required": ["space_id"]},
    {"name": "list_spaces", "description": "List all wiki spaces.", "parameters": {"visibility": {"type": "string", "enum": ["public", "private"]}}, "required": []},
    {"name": "add_page_comment", "description": "Add a comment to a wiki page.", "parameters": {"page_id": {"type": "string"}, "body": {"type": "string"}}, "required": ["page_id", "body"]},
    {"name": "resolve_page_comment", "description": "Resolve a comment on a wiki page.", "parameters": {"comment_id": {"type": "string"}}, "required": ["comment_id"]},
    {"name": "create_template", "description": "Create a wiki page template.", "parameters": {"space_id": {"type": "string"}, "name": {"type": "string"}, "body": {"type": "string"}}, "required": ["space_id", "name", "body"]},
    {"name": "apply_template", "description": "Apply a template to create a new page.", "parameters": {"template_id": {"type": "string"}, "space_id": {"type": "string"}, "title": {"type": "string"}}, "required": ["template_id", "space_id", "title"]},
    {"name": "get_page_history", "description": "Get the revision history of a wiki page.", "parameters": {"page_id": {"type": "string"}}, "required": ["page_id"]},
    {"name": "restore_page_version", "description": "Restore a previous version of a wiki page.", "parameters": {"page_id": {"type": "string"}, "version": {"type": "integer"}}, "required": ["page_id", "version"]},
    {"name": "move_page", "description": "Move a wiki page to a different parent or space.", "parameters": {"page_id": {"type": "string"}, "new_parent_id": {"type": "string"}, "new_space_id": {"type": "string"}}, "required": ["page_id"]},
    {"name": "export_page", "description": "Export a wiki page to PDF or markdown.", "parameters": {"page_id": {"type": "string"}, "format": {"type": "string", "enum": ["pdf", "markdown", "html"]}}, "required": ["page_id", "format"]},
    {"name": "set_page_permissions", "description": "Set read/write permissions on a wiki page.", "parameters": {"page_id": {"type": "string"}, "user_id": {"type": "string"}, "permission": {"type": "string", "enum": ["read", "write", "admin"]}}, "required": ["page_id", "user_id", "permission"]},
    {"name": "watch_page", "description": "Subscribe to notifications for changes to a wiki page.", "parameters": {"page_id": {"type": "string"}}, "required": ["page_id"]},
    {"name": "get_page_tree", "description": "Get the page tree (hierarchy) for a wiki space.", "parameters": {"space_id": {"type": "string"}, "depth": {"type": "integer"}}, "required": ["space_id"]},
]

# ── Base pool: 120 tools, round-robin across domains ────────────────────────

_ALL_DOMAINS = [_CALENDAR, _INVENTORY, _BILLING, _HR, _CICD, _DOCS]

_BASE_POOL: list[dict] = []
for domain in _ALL_DOMAINS:
    _BASE_POOL.extend(domain)

assert len(_BASE_POOL) == 120, f"Expected 120 base distractors, got {len(_BASE_POOL)}"

# Verify no name collisions within distractors
_distractor_names = [t["name"] for t in _BASE_POOL]
assert len(_distractor_names) == len(set(_distractor_names)), "Duplicate distractor names!"


def _expand_pool(target: int) -> list[dict]:
    """Expand beyond 120 by generating prefixed domain variants.

    Adds domain-prefixed versions (e.g., cal_create_calendar_event) and
    _v2/_bulk suffixed variants with slightly modified descriptions.
    """
    if target <= len(_BASE_POOL):
        return _BASE_POOL[:target]

    expanded = list(_BASE_POOL)
    prefixes = ["cal", "inv", "bill", "hr", "ci", "wiki"]
    suffixes = [
        ("_v2", "Version 2: "),
        ("_advanced", "Advanced version: "),
        ("_bulk", "Bulk operation: "),
    ]

    # Round 1: domain-prefixed variants
    for domain, prefix in zip(_ALL_DOMAINS, prefixes):
        if len(expanded) >= target:
            break
        for tool in domain:
            if len(expanded) >= target:
                break
            variant = {
                "name": f"{prefix}_{tool['name']}",
                "description": f"[{prefix.upper()}] {tool['description']}",
                "parameters": tool["parameters"],
                "required": tool["required"],
            }
            expanded.append(variant)

    # Round 2: suffix variants
    for suffix, desc_prefix in suffixes:
        if len(expanded) >= target:
            break
        for tool in _BASE_POOL:
            if len(expanded) >= target:
                break
            variant = {
                "name": f"{tool['name']}{suffix}",
                "description": f"{desc_prefix}{tool['description'][:1].lower()}{tool['description'][1:]}",
                "parameters": tool["parameters"],
                "required": tool["required"],
            }
            expanded.append(variant)

    return expanded[:target]


def make_distractor_set(count: int) -> list[dict]:
    """Return exactly `count` distractor tools. Deterministic."""
    pool = _expand_pool(count)
    if len(pool) < count:
        raise ValueError(
            f"Cannot generate {count} distractors; max pool size is {len(pool)}"
        )
    return pool[:count]
