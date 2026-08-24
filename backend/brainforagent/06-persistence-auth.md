# Persistence & Auth

## MongoDB

- Driver: Motor (async), `app/core/database.py`
- CA bundle: `certifi` for Atlas
- Config: `MONGODB_URI`, `MONGODB_DB` (default `kuvaka`)

---

## Store patterns

### Questionnaire (`session_store`)

- Collection: `sessions`
- Model: `ConsultationContext`
- Mongo-first read; write-through `_mem`; `_mongo_write_failed` latch
- `user_id` on doc but not on model — preserved on `$set`

### Cabin (`cabin_session_store`)

- Collection: `cabin_sessions`
- **Separate** write latch from questionnaire
- List projection omits utterances/suggestions

### Clinical patients (`patient_store`)

- Collection: `patients`
- **Mongo only** — no mem fallback
- Scoped by `doctor_id`

### Ticketing hospital (`hospital_store`)

- Collections: `ticket_hospitals`, `ticket_categories`
- `create(hospital)` seeds 15 `DEFAULT_CATEGORIES`
- Mem fallback for both hospitals and categories

### Ticketing patients (`ticket_patient_store`)

- Collection: `ticket_patients`
- **Phone globally unique** — one record across all hospitals
- `upsert(phone)` — name/age/gender only written when non-None
- Not scoped by hospital (hospital lives on `TicketSession`)

### Ticketing sessions (`ticket_session_store`)

- Collection: `ticket_sessions`, counter in `ticket_counters`
- `ticket_number`: atomic `TKT-{seq:06d}` via `find_one_and_update` on `_id: "ticket_number"`
- **Stale sweep:** `status=active` + `updated_at` > 30 min → lazily flipped to `partial` on read
- **Soft delete:** `deleted_at` set; never hard-delete
- Mem fallback + `_mem_by_ticket` index

### Users (`user_store`)

- Collection: `users`
- Roles: `doctor` (register), `hospital_admin`, `super_admin` (`create_admin`)
- `hospital_id` on admin accounts; `None` for super_admin and doctors
- `list_admins(hospital_id?)` for super_admin user management

### Refresh tokens (`refresh_store`)

- Hashed, TTL index, rotated on refresh — reuse → 401

### Cabin leases (`leases`)

- Cross-worker WS dedup; fails open

---

## Indexes (lifespan in `main.py`)

Includes ticketing:

```
ticket_hospitals:   hospital_id (unique), slug (unique)
ticket_categories:  category_id (unique), (hospital_id, active)
ticket_patients:    patient_id (unique), phone (unique)
ticket_sessions:    session_id (unique), ticket_number (unique sparse),
                    (hospital_id, started_at), patient_id, (hospital_id, status)
ticket_counters:    _id unique (built-in PK)
```

---

## Auth flow

### Doctor registration (v1)

`POST /api/v1/auth/register` → `role=doctor`, no `hospital_id`.

### Admin creation (v2)

`POST /api/v2/admin/users` (super_admin only):

- `hospital_admin` requires `hospital_id`
- `super_admin` has `hospital_id=null`

### JWT claims

```python
{
  "sub": user_id,
  "email": "...",
  "name": "...",
  "role": "doctor" | "hospital_admin" | "super_admin",
  "hospital_id": "..." | null,  # hospital_admin only
  "iat": ...,
  "exp": ...
}
```

### Dependencies

| Dep | Allows |
|-----|--------|
| `verify_token` | Any valid JWT |
| `require_hospital_admin` | `hospital_admin`, `super_admin` |
| `require_super_admin` | `super_admin` only |

---

## Multi-tenancy summary

| Store | Scope field | Notes |
|-------|-------------|-------|
| sessions | `user_id` | JWT `sub` |
| cabin_sessions | `doctor_id` | JWT `sub` |
| patients | `doctor_id` | JWT `sub` |
| ticket_sessions | `hospital_id` | slug → hospital or JWT |
| ticket_patients | phone global | shared across hospitals |

Cross-tenant → **404**.

---

## Patient clinical profile (v1)

`app/clinical/profile.py` — `build_profile()` for cabin gap alerts.

`KnownCondition.source`: `doctor` | `derived`.

Separate from ticketing `TicketPatient` — different collections and identity model.

---

## Audio (R2)

- Questionnaire: `audio_keys` on `ConsultationContext`
- Cabin: `audio_key` on `CabinSession`
- Ticketing: no audio archive in current implementation
- Unconfigured R2 → `/tmp` fallback
