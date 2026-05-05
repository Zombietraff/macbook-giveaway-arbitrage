# Database Schema

The project uses SQLite through `aiosqlite`. The canonical schema lives in
`db/database.py` as `_SCHEMA_SQL`; this document mirrors that schema for
deployment and maintenance.

## users

Main Telegram users table.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INTEGER PRIMARY KEY` | Telegram user ID |
| `username` | `TEXT` | Telegram username |
| `first_name` | `TEXT` | Telegram first name |
| `last_name` | `TEXT` | Telegram last name |
| `language_code` | `TEXT DEFAULT 'ru'` | App language, currently `ru` or `uk` |
| `is_premium` | `BOOLEAN DEFAULT FALSE` | Telegram Premium flag |
| `ref_link` | `TEXT UNIQUE` | Generated referral code |
| `ref_by` | `INTEGER` | Referrer user ID, FK to `users.id` |
| `tickets` | `REAL DEFAULT 0.0` | User ticket balance |
| `registered_at` | `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` | Registration time |
| `last_check_at` | `TIMESTAMP` | Last subscription check |
| `blocked_bot` | `BOOLEAN DEFAULT FALSE` | User blocked the bot |

## channels

Required subscription channels.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Internal ID |
| `channel_id` | `TEXT UNIQUE` | Telegram channel ID, usually `-100...` |
| `title` | `TEXT` | Display title |
| `invite_link` | `TEXT` | Join link |

## promocodes

One-time global promo codes.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Internal ID |
| `code` | `TEXT UNIQUE` | Promo code |
| `channel_id` | `INTEGER` | Optional channel binding |
| `used_by` | `INTEGER` | User who activated it, FK to `users.id` |
| `activated_at` | `TIMESTAMP` | Activation time |

## referrals

Referral relationship and status history.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Internal ID |
| `referrer_id` | `INTEGER` | Referrer user ID, FK to `users.id` |
| `referred_id` | `INTEGER` | Invited user ID, FK to `users.id` |
| `status` | `TEXT` | `pending`, `completed`, or `rejected` |
| `created_at` | `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` | Creation time |

## winners

Draw results.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Internal ID |
| `user_id` | `INTEGER` | Winner user ID, FK to `users.id` |
| `prize` | `TEXT NOT NULL` | Prize name from the configured contest prize list |
| `draw_date` | `TIMESTAMP` | Draw date |

## contest_prizes

Configurable current contest prize list. Rows are ordered by `position`; lower
positions are considered better/rarer prizes and are distributed first during
`/draw`.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Internal ID |
| `position` | `INTEGER NOT NULL` | Prize order, best first |
| `name` | `TEXT NOT NULL` | Prize display name |
| `quantity` | `INTEGER NOT NULL` | Number of winners for this prize |
| `created_by` | `INTEGER NOT NULL` | Admin/owner Telegram ID who last set the list |
| `created_at` | `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` | Creation time |

`/draw` expands rows by `quantity`, for example `2 | Prize A` and `1 | Prize B`
becomes `["Prize A", "Prize A", "Prize B"]`. If this table is empty, `/draw`
is blocked.

## settings

Key-value system settings.

| Column | Type | Notes |
| --- | --- | --- |
| `key` | `TEXT PRIMARY KEY` | Setting key |
| `value` | `TEXT` | Setting value |

Important keys:

- `end_date`: contest end date.
- `active_plugin_key`: active mini-game plugin key, for example `cherry-charm`.

## casino_spins

Spin history and accounting.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Internal ID |
| `user_id` | `INTEGER NOT NULL` | User ID, FK to `users.id` |
| `bet_amount` | `REAL NOT NULL` | Bet size |
| `dice_value` | `INTEGER NOT NULL` | Result value |
| `result_type` | `TEXT` | `loss`, `win`, or `jackpot` |
| `multiplier` | `REAL NOT NULL` | Payout multiplier |
| `balance_before` | `REAL NOT NULL` | Balance before spin |
| `balance_after` | `REAL NOT NULL` | Balance after spin |
| `created_at` | `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` | Spin time |

Indexes:

- `idx_casino_daily` on `(user_id, created_at)`.

## user_flags

Per-user service flags.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Internal ID |
| `user_id` | `INTEGER NOT NULL` | User ID, FK to `users.id` |
| `flag` | `TEXT NOT NULL` | Flag key |
| `created_at` | `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` | Creation time |

Constraints and indexes:

- Unique pair `(user_id, flag)`.
- `idx_user_flags_lookup` on `(user_id, flag)`.

Known flags:

- `webapp_disclaimer_accepted`: user accepted the WebApp entertainment disclaimer.

## user_trust_scores

Hidden owner-only draw weighting data from the Telethon userbot common-groups
check. This is never shown to users.

| Column | Type | Notes |
| --- | --- | --- |
| `user_id` | `INTEGER PRIMARY KEY` | User ID, FK to `users.id` |
| `common_chat_count` | `INTEGER DEFAULT 0` | Common groups with the configured userbot |
| `draw_multiplier` | `REAL DEFAULT 1.0` | `5.0` when `common_chat_count >= 1`, else `1.0` |
| `status` | `TEXT` | `boosted`, `plain`, `unresolvable`, `error`, or `disabled` |
| `checked_at` | `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` | Last hidden trust check |
| `error` | `TEXT` | Internal error/debug text |

`3+` common groups are counted as strong in owner stats, but still use the same
`5.0` multiplier.

## temporary_admins

Temporary operational admins managed by owner accounts.

| Column | Type | Notes |
| --- | --- | --- |
| `user_id` | `INTEGER PRIMARY KEY` | Telegram user ID |
| `username` | `TEXT` | Telegram username at time of adding |
| `first_name` | `TEXT` | Telegram first name at time of adding |
| `added_by` | `INTEGER NOT NULL` | Owner Telegram ID who added the admin |
| `created_at` | `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` | First creation time |
| `revoked_at` | `TIMESTAMP` | Null means active |

Indexes:

- `idx_temporary_admins_active` on `revoked_at`.

Access rules:

- Active temporary admin: row exists with `revoked_at IS NULL`.
- Revoked temporary admin: `revoked_at` is set and access is denied.
- Only owner accounts from `OWNER_IDS` can add or revoke temporary admins.

## admin_audit_log

Audit trail for owner and temporary admin actions.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Internal ID |
| `actor_id` | `INTEGER NOT NULL` | Telegram ID that performed the action |
| `action` | `TEXT NOT NULL` | Action key or short description |
| `target_id` | `INTEGER` | Optional target Telegram ID |
| `payload` | `TEXT` | Optional JSON/text payload |
| `created_at` | `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` | Action time |

Indexes:

- `idx_admin_audit_actor` on `(actor_id, created_at)`.
- `idx_admin_audit_action` on `(action, created_at)`.

## contest_reset_runs

Owner reset history header. One row is created every time `/reset_contest` is
confirmed.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | `INTEGER PRIMARY KEY AUTOINCREMENT` | Reset run ID |
| `actor_id` | `INTEGER NOT NULL` | Owner Telegram ID |
| `created_at` | `TIMESTAMP DEFAULT CURRENT_TIMESTAMP` | Reset time |
| `users_with_tickets_count` | `INTEGER` | Users whose tickets were archived/reset |
| `total_tickets` | `REAL` | Sum of archived tickets |
| `winners_count` | `INTEGER` | Archived winners count |
| `casino_spins_count` | `INTEGER` | Archived WebApp/casino spins count |
| `channels_count` | `INTEGER` | Archived channels count |
| `promocodes_count` | `INTEGER` | Archived promocodes count |
| `trust_scores_count` | `INTEGER` | Archived hidden trust rows count |
| `active_temp_admins_count` | `INTEGER` | Active temporary admins before reset |
| `temp_admins_count` | `INTEGER` | All temporary admin rows before reset |

## contest_reset_* archive tables

Full snapshots created before owner reset clears current contest state.

| Table | Snapshot |
| --- | --- |
| `contest_reset_user_tickets` | Users with `tickets != 0` and their ticket/check state |
| `contest_reset_winners` | All rows from `winners` |
| `contest_reset_casino_spins` | All rows from `casino_spins` |
| `contest_reset_channels` | All rows from `channels` |
| `contest_reset_promocodes` | All rows from `promocodes` |
| `contest_reset_user_trust_scores` | All rows from `user_trust_scores` |
| `contest_reset_temporary_admins` | All rows from `temporary_admins` |

Reset behavior:

- `users` are kept, but `tickets` becomes `0` and `last_check_at` becomes `NULL`.
- `contest_prizes` is kept; admins can update it explicitly with `/set_prizes`
  or clear it with `/clear_prizes`.
- `winners`, `casino_spins`, `channels`, `promocodes`, `user_trust_scores`, and `temporary_admins` are cleared.
- `settings`, `referrals`, `user_flags`, and `admin_audit_log` are not cleared.

## Plugins

Mini-games live under `plagins/<plugin_key>/` and each enabled game should have
`plugin.manifest.json`.

Current manifest fields:

| Field | Notes |
| --- | --- |
| `key` | Stable plugin key, for example `cherry-charm` |
| `name` | Human-readable name |
| `webapp_path` | Public path, `/` for the current root deploy |
| `build_dir` | Build output directory relative to plugin folder |
| `package_dir` | Package directory relative to plugin folder |
| `enabled` | Whether the plugin can be selected |

The active plugin is stored in `settings.active_plugin_key`. At the current
stage `cherry-charm` is deployed at the WebApp root; future plugins can be
served under paths such as `/apps/<plugin_key>/`.
