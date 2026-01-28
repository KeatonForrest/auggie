# PRD: Email Sequencer Integration

**Status:** Roadmap
**Priority:** TBD
**Author:** Product
**Created:** 2026-01-28

---

## Overview

Enable users to push AI-generated email sequences directly to their cold outreach tools (Instantly.io, Smartlead, Apollo.io) instead of manually copying and pasting.

## Problem Statement

Currently, Auggie generates personalized 3-email outreach sequences based on account research, but users must manually copy these emails into their sequencing tools. This creates friction and reduces the likelihood of users actually sending the sequences.

## Goals

- Reduce friction between research generation and outreach execution
- Support multiple email sequencer providers (user choice)
- Track which sequences have been sent to which platforms
- Maintain simple, non-intrusive UX

## Non-Goals

- Building our own email sending infrastructure
- Email warmup or deliverability features
- Contact enrichment (already handled separately)
- Analytics/tracking within Auggie (users track in their sequencer)

---

## Supported Providers

| Provider | Primary Focus | Strengths | API Docs |
|----------|---------------|-----------|----------|
| **Instantly.io** | Cold email | Best deliverability, built-in warmup | REST API |
| **Smartlead** | Cold email | Multi-inbox rotation, strong warmup | REST API |
| **Apollo.io** | Sales intelligence + email | All-in-one platform, contact database | REST API (already partially integrated) |

### Provider Comparison

| Feature | Instantly.io | Smartlead | Apollo.io |
|---------|--------------|-----------|-----------|
| Email Warmup | Yes | Yes | No |
| Multi-inbox Rotation | Yes | Yes (strong) | Limited |
| Contact Database | No | No | Yes (270M+) |
| Sequences API | Yes | Yes | Yes |
| Deliverability Tools | Strong | Strong | Basic |
| Pricing Model | Per-lead | Per-lead | Credits + seat |

---

## User Stories

### Connection Setup
- As a user, I want to connect my Instantly/Smartlead/Apollo account in Settings so I can send sequences directly
- As a user, I want to disconnect an account if I switch providers
- As a user, I want to see which accounts are currently connected

### Sending Sequences
- As a user, I want to send a generated email sequence to my connected sequencer with one click
- As a user, I want to specify the recipient email/name before sending
- As a user, I want to choose which connected sequencer to use (if multiple)
- As a user, I want confirmation that my sequence was sent successfully

### Tracking
- As a user, I want to see which research documents have had sequences sent
- As a user, I want a link to view the campaign in my sequencer tool

---

## User Flow

### Settings Page (Connect Account)

```
┌─────────────────────────────────────────────────────────────────┐
│  Settings                                                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Email Sequencer Integrations                                   │
│  ───────────────────────────────────────────────────────────    │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  ⚡ Instantly.io                        [Connected ✓]   │    │
│  │                                                         │    │
│  │  API Key: ••••••••••••••abc                            │    │
│  │  Workspace: My Workspace                                │    │
│  │                                         [Disconnect]    │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  📧 Smartlead                           [Connect →]     │    │
│  │                                                         │    │
│  │  Not connected                                          │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  🚀 Apollo.io                           [Connect →]     │    │
│  │                                                         │    │
│  │  Not connected                                          │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Document Page (Send Sequence)

```
┌─────────────────────────────────────────────────────────────────┐
│  Email Sequence for Acme Corp                          [X]      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  [Email 1 content...]                                           │
│  [Email 2 content...]                                           │
│  [Email 3 content...]                                           │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  [Regenerate]                    [Copy All] [Send to Sequencer] │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

         │
         ▼ Click "Send to Sequencer"

┌─────────────────────────────────────────────────────────────────┐
│  Send to Sequencer                                     [X]      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Select Provider                                                │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ ○ Instantly.io    - Best deliverability & warmup          │  │
│  │ ○ Smartlead       - Multi-inbox rotation                  │  │
│  │ ○ Apollo.io       - All-in-one (contacts + sequences)     │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  Recipient Details                                              │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ Email: john@acme.com                                      │  │
│  │ Name:  John Smith (optional)                              │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  Campaign Options                                               │
│  [ ] Add to existing campaign: [Select Campaign ▼]              │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│                              [Cancel]  [Send Sequence]          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

         │
         ▼ Success

┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  ✓ Sequence sent to Instantly.io                               │
│                                                                 │
│  Campaign: "Acme Corp - Jan 2026"                              │
│  Recipient: john@acme.com                                       │
│                                                                 │
│  [View in Instantly →]                          [Done]          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Technical Architecture

### System Flow

```
┌────────┐          ┌────────┐          ┌──────────┐          ┌───────────┐
│ User   │          │ Auggie │          │ Sequencer│          │ Provider  │
│Browser │          │ API    │          │ Service  │          │ API       │
└───┬────┘          └───┬────┘          └────┬─────┘          └─────┬─────┘
    │                   │                    │                      │
    │ POST /send        │                    │                      │
    │ {doc_id, email,   │                    │                      │
    │  provider}        │                    │                      │
    │──────────────────>│                    │                      │
    │                   │                    │                      │
    │                   │ get_document()     │                      │
    │                   │ get_connection()   │                      │
    │                   │───────────────────>│                      │
    │                   │                    │                      │
    │                   │ send_sequence()    │                      │
    │                   │───────────────────>│                      │
    │                   │                    │                      │
    │                   │                    │ POST /campaign       │
    │                   │                    │─────────────────────>│
    │                   │                    │                      │
    │                   │                    │ POST /lead           │
    │                   │                    │─────────────────────>│
    │                   │                    │                      │
    │                   │                    │ {campaign_id}        │
    │                   │                    │<─────────────────────│
    │                   │                    │                      │
    │                   │ save_campaign()    │                      │
    │                   │<───────────────────│                      │
    │                   │                    │                      │
    │ {success, url}    │                    │                      │
    │<──────────────────│                    │                      │
```

### File Structure

```
auggie/
├── config.py                    # + API key settings
├── database.py                  # + sequencer tables
├── main.py                      # + sequencer endpoints
├── services/
│   ├── sequencer.py             # NEW: Multi-provider abstraction
│   └── apollo.py                # + sequence methods (existing file)
└── templates/
    ├── settings.html            # + integrations section
    └── document.html            # + send to sequencer button/modal
```

---

## Data Models

### sequencer_connections

Stores user's connected sequencer accounts.

```sql
CREATE TABLE sequencer_connections (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Provider info
    provider TEXT NOT NULL,  -- 'instantly', 'smartlead', 'apollo'
    api_key TEXT NOT NULL,   -- Encrypted
    workspace_id TEXT,       -- Provider-specific (optional)

    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    last_verified_at TIMESTAMPTZ,

    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(user_id, provider)
);

CREATE INDEX idx_sequencer_connections_user ON sequencer_connections(user_id);
```

### email_campaigns

Tracks sequences sent to external platforms.

```sql
CREATE TABLE email_campaigns (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    document_id BIGINT NOT NULL REFERENCES research_documents(id) ON DELETE CASCADE,

    -- Provider info
    provider TEXT NOT NULL,           -- 'instantly', 'smartlead', 'apollo'
    external_campaign_id TEXT,        -- ID from the sequencer API
    external_campaign_url TEXT,       -- Direct link to campaign

    -- Recipient
    recipient_email TEXT NOT NULL,
    recipient_name TEXT,

    -- Status
    status TEXT DEFAULT 'sent',       -- 'sent', 'failed'
    error_message TEXT,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_email_campaigns_user ON email_campaigns(user_id);
CREATE INDEX idx_email_campaigns_document ON email_campaigns(document_id);
```

---

## API Endpoints

### Connection Management

```
POST   /api/sequencer/connect
       Body: { provider, api_key, workspace_id? }
       Response: { success, connection }

DELETE /api/sequencer/disconnect/{provider}
       Response: { success }

GET    /api/sequencer/connections
       Response: { connections: [...] }

POST   /api/sequencer/verify/{provider}
       Response: { success, valid, error? }
```

### Sequence Operations

```
GET    /api/sequencer/{provider}/campaigns
       Response: { campaigns: [...] }
       (List existing campaigns for "add to existing" feature)

POST   /document/{doc_id}/send-sequence
       Body: { provider, recipient_email, recipient_name?, campaign_id? }
       Response: { success, campaign_url, external_id }

GET    /document/{doc_id}/campaigns
       Response: { campaigns: [...] }
       (List sequences sent from this document)
```

---

## Configuration

### Environment Variables

```bash
# Instantly.io (optional - users provide their own keys)
# No server-side keys needed

# Smartlead (optional - users provide their own keys)
# No server-side keys needed

# Apollo.io - already exists
APOLLO_API_KEY=xxx  # For contact enrichment (existing)
# Users connect their own Apollo accounts for sequences
```

### Settings Model Addition

```python
# config.py - No changes needed
# User API keys stored in database (sequencer_connections table)
# encrypted at rest
```

---

## Implementation Tasks

### Phase 1: Backend Foundation
- [ ] Add `sequencer_connections` table to database.py
- [ ] Add `email_campaigns` table to database.py
- [ ] Create `services/sequencer.py` with provider abstraction
- [ ] Implement Instantly.io provider
- [ ] Implement Smartlead provider
- [ ] Implement Apollo.io sequences (extend existing apollo.py)
- [ ] Add connection management endpoints to main.py
- [ ] Add send-sequence endpoint to main.py

### Phase 2: Frontend - Settings
- [ ] Add "Email Sequencer Integrations" section to settings.html
- [ ] Create connect/disconnect UI for each provider
- [ ] Add API key input modals
- [ ] Show connection status indicators

### Phase 3: Frontend - Document Page
- [ ] Add "Send to Sequencer" button to outreach modal
- [ ] Create provider selection modal
- [ ] Create recipient input form
- [ ] Add success/error states
- [ ] Show "View in [Provider]" link after send

### Phase 4: Polish & Testing
- [ ] Add loading states for all async operations
- [ ] Handle API errors gracefully
- [ ] Add rate limiting considerations
- [ ] Test with real accounts on each provider
- [ ] Add "campaigns sent" indicator on document cards

---

## Security Considerations

1. **API Key Storage**: User API keys must be encrypted at rest in the database
2. **Key Validation**: Verify API keys work before saving connection
3. **Scoped Access**: Users can only access their own connections/campaigns
4. **Key Rotation**: Allow users to update API keys without losing history
5. **Audit Trail**: Log all send operations for debugging

---

## Future Enhancements

1. **Bulk Send**: Send sequence to multiple contacts at once
2. **Template Mapping**: Map Auggie emails to existing sequencer templates
3. **Sync Status**: Pull campaign stats back into Auggie
4. **Auto-Send**: Option to automatically send after research generation
5. **More Providers**: Outreach.io, Salesloft, HubSpot Sequences

---

## Open Questions

1. Should we support OAuth for providers that offer it, or stick with API keys?
2. Do we need to sync campaign status back (opens, replies)?
3. Should "Send to Sequencer" cost a credit, or is it free after research?
4. How do we handle provider API rate limits?

---

## References

- [Instantly.io API Docs](https://developer.instantly.ai/)
- [Smartlead API Docs](https://api.smartlead.ai/reference)
- [Apollo.io API Docs](https://apolloio.github.io/apollo-api-docs/)
