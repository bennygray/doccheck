## Requirements

### Requirement: Admin user list API
The system SHALL provide `GET /api/admin/users` that returns all users as `UserPublic[]` (id, username, role, is_active, must_change_password, created_at). Only admin role SHALL have access; reviewer calls SHALL receive 403.

#### Scenario: Admin fetches user list
- **WHEN** admin calls `GET /api/admin/users`
- **THEN** response is 200 with array of all users (excluding password_hash)

#### Scenario: Reviewer denied access
- **WHEN** reviewer calls `GET /api/admin/users`
- **THEN** response is 403

### Requirement: Admin create user API
The system SHALL provide `POST /api/admin/users` accepting `{username, password, role}`. Username MUST be unique (409 on duplicate). Password MUST be ≥8 chars with at least one letter and one digit (422 on violation). Role MUST be "admin" or "reviewer" (422 otherwise). Created user SHALL have `must_change_password=true` and `is_active=true`. Only admin role SHALL have access.

#### Scenario: Create reviewer successfully
- **WHEN** admin calls `POST /api/admin/users` with valid username/password/role="reviewer"
- **THEN** response is 201 with UserPublic, user can immediately login

#### Scenario: Duplicate username
- **WHEN** admin calls `POST /api/admin/users` with existing username
- **THEN** response is 409

#### Scenario: Weak password
- **WHEN** admin calls `POST /api/admin/users` with password "12345678" (no letters)
- **THEN** response is 422

#### Scenario: Invalid role
- **WHEN** admin calls `POST /api/admin/users` with role="superadmin"
- **THEN** response is 422

### Requirement: Admin disable/enable user API
The system SHALL provide `PATCH /api/admin/users/{id}` accepting `{is_active?, role?}`. Admin MUST NOT be able to disable themselves (400). Disabling a user SHALL cause their existing JWT to fail on next request (existing `get_current_user` checks `is_active`). Only admin role SHALL have access.

#### Scenario: Disable a user
- **WHEN** admin calls `PATCH /api/admin/users/{id}` with `{is_active: false}`
- **THEN** response is 200, target user's subsequent API calls return 403

#### Scenario: Admin cannot disable self
- **WHEN** admin calls `PATCH /api/admin/users/{id}` where id is their own
- **WITH** `{is_active: false}`
- **THEN** response is 400

#### Scenario: Change user role
- **WHEN** admin calls `PATCH /api/admin/users/{id}` with `{role: "admin"}`
- **THEN** response is 200, user role updated

#### Scenario: User not found
- **WHEN** admin calls `PATCH /api/admin/users/99999`
- **THEN** response is 404

### Requirement: Admin users frontend page
The system SHALL provide an `/admin/users` page accessible only to admin users. The page SHALL display a user table (username, role, status, created_at), a "Create User" button that opens a creation form, and an enable/disable toggle per row. Non-admin users navigating to `/admin/users` SHALL be redirected to `/projects`.

#### Scenario: Admin views user list
- **WHEN** admin navigates to `/admin/users`
- **THEN** page displays user table with all users

#### Scenario: Admin creates user via form
- **WHEN** admin clicks "Create User", fills form, and submits
- **THEN** new user appears in table

#### Scenario: Admin toggles user status
- **WHEN** admin clicks disable toggle on a user row
- **THEN** user status changes to disabled, toggle reflects new state

#### Scenario: Non-admin redirected
- **WHEN** reviewer navigates to `/admin/users`
- **THEN** redirected to `/projects`
