# Admin Guide - MVP Admin UX Features

This guide covers the new admin features for worker password management, client management, and booking creation.

> **Note**: Admin API calls are now authenticated at the reverse proxy. Requests must include the
> `X-Admin-User`/`X-Admin-Email` headers injected by the proxy; direct backend access is rejected.

## Table of Contents

1. [Worker Password Management](#worker-password-management)
2. [Worker Login](#worker-login)
3. [Client Management](#client-management)
4. [Booking Creation](#booking-creation)
5. [Inventory Low Stock](#inventory-low-stock)
6. [Inventory Suppliers](#inventory-suppliers)
7. [Troubleshooting](#troubleshooting)

---

## Worker Password Management

### Creating a Worker with Password

**URL**: `/v1/admin/ui/workers/new`

**Steps**:

1. Navigate to the Workers section in the admin panel
2. Click "New worker" button
3. Fill in the form:
   - **Name** (required): Worker's full name
   - **Phone** (required): Worker's phone number (used for login)
   - **Password** (required): Secure password (minimum 8 characters)
   - **Email** (optional): Worker's email address
   - **Role** (optional): Job role/title
   - **Hourly rate** (optional): Rate in cents per hour
   - **Team** (required): Select the team this worker belongs to
   - **Active** (checkbox): Mark as active (checked by default)
4. Click "Save worker"

**Important Notes**:
- The password is securely hashed using Argon2id before storage
- Plain text passwords are never stored in the database
- Phone numbers must be unique across workers
- Password must be at least 8 characters long

**Example cURL** (for API access):
```bash
curl -X POST https://your-domain.com/v1/admin/ui/workers/new \
  -H "X-Admin-User: admin@example.com" \
  -H "X-Admin-Email: admin@example.com" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "name=John Doe" \
  -d "phone=+1234567890" \
  -d "password=SecurePass123" \
  -d "email=john@example.com" \
  -d "team_id=1" \
  -d "is_active=on"
```

### Editing Worker Password

**URL**: `/v1/admin/ui/workers/{worker_id}`

**Steps**:

1. Navigate to the Workers section
2. Click on the worker's name to edit
3. To change password:
   - Enter a new password in the "Password" field
   - Leave blank to keep the current password
4. Update other fields as needed
5. Click "Save worker"

**Important Notes**:
- Password field shows a hint: "Leave blank to keep current password"
- Changing the password will log out the worker from all active sessions
- Password must still be at least 8 characters if provided

---

## Worker Login

### Worker Authentication

Workers can now authenticate using their phone number and password.

**Login URL**: `/worker/login` (or worker portal URL configured in your system)

**Authentication Methods**:

1. **Phone + Password** (Database-backed):
   - Username: Worker's phone number
   - Password: Password set in admin panel

2. **Legacy Environment Variables** (Backward compatible):
   - Still supported for workers configured via `WORKER_BASIC_USERNAME` and `WORKER_BASIC_PASSWORD`

**Login Flow**:

1. Worker navigates to the worker portal
2. Enters phone number as username
3. Enters password
4. System validates credentials:
   - Checks password hash in database
   - Returns 401 if invalid
   - Creates session token on success
5. Worker is redirected to their job dashboard

**Error Messages**:

- `"Invalid phone or password"` - Credentials don't match any active worker
- `"Worker authentication not configured. Please contact your administrator."` - Worker exists but has no password set
- `"Session expired"` - Session token is no longer valid

**Example cURL**:
```bash
# Login request
curl -X POST https://your-domain.com/worker/login \
  -u "+1234567890:SecurePass123"

# The response will include a session cookie for subsequent requests
```

**Security Features**:
- Passwords are hashed using Argon2id (or Bcrypt/SHA256 for legacy)
- Automatic password hash upgrades on login
- Constant-time comparison to prevent timing attacks
- Session tokens are HMAC-signed with expiration
- Failed login attempts are logged for audit

---

## Client Management

### Creating a Client

**URL**: `/v1/admin/ui/clients/new`

**Steps**:

1. Navigate to the Clients section in the admin panel
2. Click "New client" button
3. Fill in the form:
   - **Name** (optional): Client's full name
   - **Phone** (optional): Contact phone number
   - **Email** (required): Client's email address
   - **Address** (optional): Client's address
   - **Notes** (optional): Any additional notes about the client
4. Click "Save client"

**Important Notes**:
- Email is the only required field
- Clients are automatically scoped to your organization
- Client data is isolated per organization (multi-tenant safe)

**Example cURL**:
```bash
curl -X POST https://your-domain.com/v1/admin/ui/clients/new \
  -H "X-Admin-User: admin@example.com" \
  -H "X-Admin-Email: admin@example.com" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "name=Jane Smith" \
  -d "phone=+1987654321" \
  -d "email=jane@example.com" \
  -d "address=123 Main St, City, State 12345" \
  -d "notes=Prefers morning appointments"
```

### Viewing and Searching Clients

**URL**: `/v1/admin/ui/clients`

**Features**:
- List all clients in your organization
- Search by name, phone, or email
- Click on client name to edit details

**Search Example**:
```bash
# Search for clients
curl "https://your-domain.com/v1/admin/ui/clients?q=jane" \
  -H "X-Admin-User: admin@example.com" \
  -H "X-Admin-Email: admin@example.com"
```

### Editing a Client

**URL**: `/v1/admin/ui/clients/{client_id}`

**Steps**:
1. Navigate to Clients section
2. Click on the client you want to edit
3. Update fields as needed
4. Click "Save client"

---

## Booking Creation

### Creating a Booking from Admin UI

**URL**: `/v1/admin/ui/bookings/new`

**Steps**:

1. Navigate to `/v1/admin/ui/bookings/new`
2. Fill in the booking form:
   - **Team** (required): Select which team will handle this booking
   - **Client** (optional): Select an existing client from dropdown (must belong to your organization)
   - **Assigned Worker** (optional): Pre-assign a worker to this booking
   - **Start Date & Time** (required): When the booking starts
   - **Duration** (required): Duration in minutes (default: 120)
3. Click "Create Booking"

**Important Notes**:
- Client must belong to your organization (org-scoped validation enforced)
- If no client is selected, booking will be created without a client reference
- Worker assignment is optional - can be assigned later via dispatch board
- Start time is in UTC timezone
- Duration must be at least 30 minutes
- Booking is created with "PENDING" status by default
- For address/notes, these should be associated with the client record (see Client Management section)

**Example cURL**:
```bash
curl -X POST https://your-domain.com/v1/admin/ui/bookings/create \
  -H "X-Admin-User: admin@example.com" \
  -H "X-Admin-Email: admin@example.com" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "team_id=1" \
  -d "client_id=abc-123-def-456" \
  -d "assigned_worker_id=5" \
  -d "starts_at=2026-01-15T10:00" \
  -d "duration_minutes=120"
```

**After Creation**:
- You'll be redirected to the dispatch board for the booking's date
- The booking will appear in the dispatch view
- You can assign/reassign workers from the dispatch board
- Booking ID is automatically generated as a UUID

**Validation Rules**:
- Team must exist and belong to your organization
- Client (if specified) must exist and belong to your organization
- Worker (if specified) must exist and belong to your organization
- Duration must be a positive integer (minimum 30 minutes)
- Start date/time must be valid ISO 8601 format

**Error Messages**:
- `"Client not found or does not belong to your organization"` - Attempting to assign a client from a different org
- `"Team not found"` - Team doesn't exist or belongs to different org
- `"Worker not found"` - Worker doesn't exist or belongs to different org

---

## Inventory Low Stock

The Inventory page now includes a Low Stock panel to surface items at or below their minimum quantity.

**How it works:**
- Items are flagged as low stock when current quantity is less than or equal to the minimum quantity.
- Use the “Mark as ordered” action to quickly tag items that are already on order.
- Jump to Purchase Orders to build supplier-ready orders with line totals and taxes.

**Tips:**
- Use the “Low stock only” checkbox to filter the main inventory table to items that need reordering.

## Inventory Purchase Orders

Purchase orders help you plan replenishment, confirm totals, and receive items back into stock.

**How it works:**
- Create a draft by selecting a supplier, adding line items, and confirming tax/shipping totals.
- Use “Mark ordered” when the PO is submitted to the supplier, then “Mark received” once goods arrive.
- Drafts can be edited until they are marked ordered.

**Tips:**
- Review the totals card before submitting to ensure tax and shipping are correct.
- Use the Purchase Orders list filters to track open orders by supplier and status.

## Inventory Suppliers

The Inventory Suppliers page keeps a directory of preferred vendors for reordering.

**How it works:**
- Search by supplier name, email, or phone to find vendors quickly.
- Capture delivery days, ordering terms, minimum order amounts, and internal notes.
- Use Create/Edit/Delete actions (requires inventory manage permission) to maintain the list.

**Tips:**
- Store delivery cadence (e.g., “Mon/Wed/Fri”) in the Delivery Days field for quick reorder planning.
- Use the Notes field for rep names, pickup instructions, or preferred order channels.

## Troubleshooting

### Common Issues

#### 401 Unauthorized Errors

**Symptom**: Worker cannot log in, receives "Invalid phone or password" error

**Possible Causes**:
1. Password not set for worker in admin panel
2. Wrong phone number format
3. Incorrect password

**Solution**:
1. Verify worker exists: Check `/v1/admin/ui/workers`
2. Ensure password is set: Edit worker and set/reset password
3. Check phone format matches exactly what was entered during worker creation
4. Check logs for authentication attempts

**Log Location**: Look for `worker_auth` entries in application logs

#### 500 Internal Server Errors

**Symptom**: Form submission fails with 500 error

**Possible Causes**:
1. Database migration not applied
2. Missing required fields
3. Organization ID not set correctly

**Solution**:
1. Run migrations: `alembic upgrade head`
2. Check `/readyz` endpoint for migration status
3. Verify request includes all required fields
4. Check application logs for detailed error message

**Log Location**: Application error logs, database query logs

#### Worker Authentication Not Configured

**Symptom**: Worker login shows "Worker authentication not configured" error

**Possible Cause**: Worker exists but `password_hash` field is NULL

**Solution**:
1. Edit the worker in admin panel
2. Set a password (minimum 8 characters)
3. Save the worker
4. Ask worker to try logging in again

#### Cross-Organization Data Leaks

**Symptom**: Seeing data from other organizations

**This should NEVER happen** - all routes are org-scoped

**If this occurs**:
1. Immediately check application logs
2. Verify RLS policies are enabled: `SELECT * FROM pg_policies;`
3. Check `current_org_id` is being set correctly
4. Review middleware stack in `/v1/admin/profile`

**Prevention**:
- All database queries filter by `org_id`
- Postgres RLS provides defense-in-depth
- Admin audit logs track all actions

### Health Check Endpoint

**URL**: `/readyz`

**Purpose**: Verify system health and migration status

**Example**:
```bash
curl https://your-domain.com/readyz
```

**Expected Response**:
```json
{
  "status": "ready",
  "db_connected": true,
  "migrations_current": true,
  "current_revision": "0065",
  "expected_revision": "0065"
}
```

**If migrations are out of sync**:
```bash
# Backend directory
cd backend

# Run pending migrations
alembic upgrade head

# Verify
curl https://your-domain.com/readyz
```

### Where to Find Logs

**Application Logs**:
- Standard output/error streams
- Look for structured JSON logs with context fields:
  - `org_id`: Organization identifier
  - `user_id`: User/worker identifier
  - `action`: Admin action type
  - `role`: User role

**Admin Audit Logs** (Database):
```sql
SELECT * FROM admin_audit_logs
WHERE org_id = 'your-org-id'
ORDER BY created_at DESC
LIMIT 50;
```

**Worker Authentication Events**:
```bash
# Search logs for worker auth events
grep "worker_auth" application.log

# Look for specific phone number
grep "+1234567890" application.log
```

### Security Checklist

✅ **Do's**:
- Always use HTTPS in production
- Enforce password minimum length (8+ characters)
- Regularly review admin audit logs
- Use strong admin credentials
- Enable MFA for admin accounts if available

❌ **Don'ts**:
- Never log plain text passwords
- Never disable org_id scoping
- Don't share worker credentials
- Don't bypass CSRF protection
- Don't commit `.env` files with secrets

---

## Migration Guide

### Running Migrations

After deploying this update, run migrations:

```bash
# Navigate to backend directory
cd backend

# Check current migration status
alembic current

# Run migrations
alembic upgrade head

# Verify /readyz returns healthy
curl http://localhost:8000/readyz
```

### New Environment Variables

No new environment variables are required for this feature set. Existing variables are used:

- `DEFAULT_ORG_ID`: Default organization for workers/clients
- `WORKER_PORTAL_SECRET`: Secret for worker session tokens
- `PASSWORD_HASH_SCHEME`: Password hashing scheme (default: argon2id)

### Database Changes

**New Columns**:
- `workers.password_hash` (nullable varchar(255))
- `workers` index on `phone`
- `client_users.org_id` (uuid, FK to organizations)
- `client_users.phone` (nullable varchar(50))
- `client_users.address` (nullable varchar(500))
- `client_users.notes` (nullable text)
- `client_users.updated_at` (timestamp)

**Backward Compatibility**:
- Existing workers without password can still use env-based auth
- Password field is nullable to support gradual migration
- Client users are backfilled with first organization's org_id

---

## Manual Verification Steps

### Worker Password Flow

1. Create a worker with password:
   ```bash
   curl -X POST http://localhost:8000/v1/admin/ui/workers/new \
     -u "admin:password" \
     -d "name=Test Worker" \
     -d "phone=+1555000001" \
     -d "password=TestPass123" \
     -d "team_id=1" \
     -d "is_active=on"
   ```

2. Verify worker can login:
   ```bash
   curl -X GET http://localhost:8000/worker \
     -u "+1555000001:TestPass123"
   ```

3. Verify worker sees assigned bookings
4. Update worker password via admin UI
5. Verify old password no longer works
6. Verify new password works

### Client Management Flow

1. Create a client:
   ```bash
   curl -X POST http://localhost:8000/v1/admin/ui/clients/new \
     -u "admin:password" \
     -d "name=Test Client" \
     -d "email=test@example.com" \
     -d "phone=+1555000002"
   ```

2. Search for client:
   ```bash
   curl "http://localhost:8000/v1/admin/ui/clients?q=test" \
     -u "admin:password"
   ```

3. Verify client is org-scoped (should not appear for other orgs)

### Booking Creation Flow

1. Create a booking:
   ```bash
   curl -X POST http://localhost:8000/v1/admin/ui/bookings/create \
     -u "admin:password" \
     -d "team_id=1" \
     -d "starts_at=2026-01-20T10:00" \
     -d "duration_minutes=120"
   ```

2. Verify booking appears in dispatch board
3. Verify booking can be assigned to worker
4. Verify org-scoping (booking should not be visible to other orgs)

---

## Support

For issues or questions:
1. Check this guide first
2. Review application logs
3. Check admin audit logs for action history
4. Verify migrations are current via `/readyz`
5. Report issues with:
   - Exact error message
   - Steps to reproduce
   - Log excerpts (sanitized)
   - Expected vs actual behavior
