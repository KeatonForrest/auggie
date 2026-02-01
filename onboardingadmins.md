# Admin Roles Guide

Auggie has two admin tiers: **Super Admin** (platform-level) and **Org Admin** (team-level).

---

## Super Admin

Platform-wide access for the app creator/maintainer. Accessed at `/admin`.

### How to grant

```sql
UPDATE users SET is_admin = true WHERE email = 'your@email.com';
```

### What they can do

- **See every user** on the platform — email, name, org, credit balance, doc count, list count, join date
- **Search users** by email or name
- **Toggle admin** on any user (grant or revoke super admin)
- **Add credits** to any user's org
- **Impersonate any user** — swap your session to see the app as they see it, with an orange banner and "Exit" button to return
- **Monitor the task queue** — pending, running, failed, and completed counts
- **View failed tasks** with error messages and retry them
- **See all organizations** with member counts and credit balances
- **View total revenue** and monthly purchase breakdown

### Visibility

- Non-admins get a 404 on `/admin` (the route appears to not exist)
- The "Admin" nav link only appears for super admins
- All action endpoints (`toggle-admin`, `add-credits`, `impersonate`, `retry`) return 404 for non-admins

---

## Org Admin

Team-level management for each organization. Accessed at `/settings/team`.

### How to grant

Any existing org admin can promote a member to admin via the team settings page. The user who creates an org is automatically its first admin.

### What they can do

- **Invite members** by email with a role (admin, member, or viewer)
- **Remove members** from their org
- **Change member roles** — promote or demote within their org
- **Revoke pending invites**
- **View per-member usage** — research count and last activity for each team member (`/settings/team/usage`)

### What they cannot do

- See other organizations or their members
- See other users outside their org
- Access revenue, billing, or task queue data
- Impersonate users
- Grant super admin status

---

## Role comparison

| Capability | Super Admin | Org Admin | Member/Viewer |
|---|---|---|---|
| View all platform users | Yes | No | No |
| Manage any org's credits | Yes | No | No |
| Impersonate users | Yes | No | No |
| Monitor task queue | Yes | No | No |
| View platform revenue | Yes | No | No |
| Invite team members | Yes (via impersonation) | Yes | No |
| Remove team members | Yes (via impersonation) | Yes | No |
| Change team roles | Yes (via impersonation) | Yes | No |
| View team usage | Yes (via impersonation) | Yes | No |
| Run research | Yes | Yes | Yes |
