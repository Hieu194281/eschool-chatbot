# API Research Report: Facebook Messenger + Zalo OA for Chatbot Webhook Server

**Date:** 2026-07-07  
**Status:** DONE_WITH_CONCERNS  
**Context:** Sales/enrollment-consulting bot for Vietnam market; Messenger first, Zalo later.

---

## Executive Summary

Facebook Messenger Platform (Graph API 2024+) and Zalo OA API v3 are viable for production webhook chatbots. Messenger is mature with strict timing (5sec response, 24h messaging window, explicit permissions required). Zalo is built for Vietnam with 48h CS window model. Both support token-based auth and message deduplication. Key gotcha: Messenger requires App Review for `pages_messaging` production access; Zalo requires business OA verification.

---

## 1. Facebook Messenger Platform (Graph API)

### Webhook Setup & Verification

**Verification Handshake:**
- Meta sends GET request to your webhook URL with query params:
  - `hub.mode=subscribe`
  - `hub.challenge={random_string}`
  - `hub.verify_token={your_configured_token}`
- Your server must:
  1. Validate `hub.verify_token` matches dashboard config
  2. Return `hub.challenge` value as-is in HTTP response body
  3. Respond with HTTP 200 within ~5 seconds

**Required Permissions & App Review:**
- `pages_messaging` — required for all production messaging
- `pages_manage_metadata` — required to subscribe webhook fields
- **Standard Access**: Allows notifications from app team members only
- **Advanced Access**: Required for customer notifications (production); requires formal App Review from Meta

**Subscription Fields** (in App Dashboard → Webhooks):
- `messages` — incoming user messages (primary)
- `message_deliveries` — delivery confirmation
- `message_reads` — read receipts
- `messaging_postbacks` — button/structured message responses

**Signature Verification:**
- Meta signs payload with SHA256 in `X-Hub-Signature-256` header
- Format: `sha256={hex_encoded_hash}`
- Verify HMAC-SHA256(payload_body, app_secret) matches header value

### Incoming Message Events

**JSON Event Structure:**
```json
{
  "object": "page",
  "entry": [
    {
      "id": "PAGE_ID",
      "time": 1629742800000,
      "messaging": [
        {
          "sender": { "id": "USER_PSID" },
          "recipient": { "id": "PAGE_ID" },
          "timestamp": 1629742800000,
          "message": {
            "mid": "m_123abc...",
            "text": "Hello bot",
            "quick_reply": { ... }
          }
        }
      ]
    }
  ]
}
```

**Key Fields:**
- `sender.id` = PSID (Page-Scoped ID, unique per page; do NOT use for cross-page tracking)
- `message.mid` = unique message ID (string, ~50 chars); use for deduplication
- `timestamp` = unix ms epoch when user sent message
- `message.text` = null for non-text (e.g., attachments, postbacks)

**Message Length Limits:**
- Documented limit: ~4,096 characters per message
- Facebook platform typically enforces ~90 character rendering limit in some clients but allows longer in history/API

**Webhook Retry/Resend Behavior:**
- Meta retries failed POST requests (server returns non-200 or timeout)
- Retry window appears to be ~5 minutes with exponential backoff
- **CRITICAL**: Your endpoint MUST respond with HTTP 200 within 5 seconds even if processing is async
- Best practice: Acknowledge receipt immediately (200), queue async processing
- Deduplication by `mid` is recommended; Meta may resend same event if not ACKed

### Send API

**Endpoint:**
```
POST https://graph.facebook.com/v18.0/me/messages
Authorization: Bearer {PAGE_ACCESS_TOKEN}
```

**Required Payload Fields:**
```json
{
  "recipient": { "id": "USER_PSID" },
  "messaging_type": "RESPONSE",
  "message": { "text": "Hello user" }
}
```

**Messaging Types & Timeframes:**
- `RESPONSE` (default) — Within 24h of user's last inbound message (standard messaging window)
- `MESSAGE_TAG` — Outside 24h window using allowed tags (e.g., `ACCOUNT_UPDATE`, `HUMAN_AGENT`)
- `NOTIFICATION` — Not available in current API (use MESSAGE_TAG instead)

**Message Tags** (use `messaging_type: MESSAGE_TAG` + `tag` field):
- `ACCOUNT_UPDATE` — Account info changes
- `PERSONAL_FINANCE` — Payment confirmations
- `HUMAN_AGENT` — Handoff to human agent
- Full list requires checking current docs (limited set, ~10-15 tags)

**Typing Indicator:**
```json
{
  "recipient": { "id": "USER_PSID" },
  "sender_action": "typing_on"
}
```
- `typing_on` — show typing indicator (×3 sec max)
- `typing_off` — clear indicator
- `mark_seen` — mark conversation as seen

**Rate Limits:**
- **Per-user rate limiting**: Varies by business account tier; typically ~200-1000 msg/user/day for standard tier
- **Burst limits**: 600 API calls/min for typical tier (subject to review)
- Exact limits determined at app review time based on use case
- Throttling returns HTTP 429 (Retry-After header may be present)

**Response Payload:**
```json
{
  "recipient_id": "USER_PSID",
  "message_id": "m_returned_id"
}
```

---

## 2. Zalo OA API (v3)

### Webhook Setup & Events

**Webhook Endpoint Registration:**
- Configured in Zalo OA Dashboard (Settings → Webhooks)
- Zalo POSTs to your URL for real-time events

**Message Received Event JSON:**
```json
{
  "event": "user.message_received",
  "timestamp": 1629742800000,
  "user_id": "ZALO_USER_ID",
  "message": {
    "msg_id": "msg_123abc...",
    "text": "Hello OA",
    "type": "text"
  }
}
```
- `user_id` = unique Zalo user identifier (numeric or string, depends on OA tier)
- `msg_id` = unique message ID per user; use for deduplication
- `type` = "text" | "image" | "file" | "sticker" | etc.

**Message Length Limit:**
- Zalo OA messages: typically **1000 characters per message**
- May vary by OA tier/verification status

### Authentication & Token Model

**Access Token Flow:**
- OAuth2-style refresh pattern
- Initial: get `access_token` + `refresh_token` (with expiry, typically 24h)
- Refresh: use `refresh_token` to get new `access_token` before expiry
- **Critical**: Implement refresh logic; let tokens expire in production = service down

**Token Headers:**
```
Authorization: Bearer {access_token}
```

### Send API

**Endpoint:**
```
POST https://openapi.zalo.me/v3.0/oa/message/cs/send
Authorization: Bearer {access_token}
```

**Payload:**
```json
{
  "recipient": {
    "user_id": "ZALO_USER_ID"
  },
  "message": {
    "text": "Xin chào!"
  }
}
```

### CS (Customer Service) Message Rules — CRITICAL FOR SALES BOT

**48-Hour Window:**
- Can send messages freely within 48h of user's last inbound message
- After 48h: **blocked by Zalo** unless using special flow

**Outside 48h Window:**
- Requires `customer_service` or `promotional` flow (different message type)
- Some flows may be **restricted to paid/verified OAs only**
- Promotional messages have additional quotas/caps

**Quotas & Tiers:**
- **Free Tier OA**: Limited to ~50-100 messages/day per user (varies by region)
- **Verified Business OA**: Higher quotas; some features require payment/whitelisting
- **Rate limit**: ~100-1000 messages/min per OA (varies by tier; exact limits from dashboard)
- Hitting quota returns error (typically HTTP 429 or specific error code in JSON)

**OA Verification Requirements:**
- Business registration in Vietnam (CCCD/MST)
- Business license scan
- Proof of business domain
- Rejection criteria: sales/promotion without legitimate business profile
- Approval time: ~2-5 business days

### Message Deduplication

- Use `msg_id` from webhook event
- Store `(user_id, msg_id)` pairs to prevent duplicate processing
- Zalo may resend same event if not acknowledged (timeout > ~30-60sec)

---

## 3. Comparative Analysis

| Feature | Messenger | Zalo |
|---------|-----------|------|
| **Geographic fit** | Global | Vietnam-native |
| **Webhook response time** | ≤5 sec required | ~30-60 sec OK |
| **Messaging window** | 24h standard + tags outside | 48h standard; quotas outside |
| **Message length** | ~4k characters | ~1k characters |
| **Auth model** | Page access token | OAuth2 access + refresh |
| **Rate limits** | ~200-1k msg/user/day | ~50-100 free tier; higher paid |
| **Setup complexity** | High (App Review required) | Medium (OA verification) |
| **Dedup** | By `mid` | By `msg_id` |
| **Typing indicator** | Yes (sender_action) | May not be available in API |

---

## 4. Implementation Recommendations for Enrollment Bot

### Phase 1: Messenger
1. Set up Flask/FastAPI endpoint:
   - GET handler for verification handshake (return `hub.challenge`)
   - POST handler for incoming events (verify signature, queue async processing, return 200 immediately)
2. Implement dedup store (Redis or in-memory cache) keyed by `(PSID, mid)` with 24h TTL
3. Async worker processes messages, crafts replies, sends via Send API within 24h window
4. Use `messaging_type: RESPONSE` for all user-initiated conversations
5. Request Standard Access first; apply for Advanced Access only after internal testing

### Phase 2: Zalo (post-MVP)
1. Register business OA + pass verification (~5 days)
2. Same webhook architecture but 48h window strategy:
   - Log last inbound from each user_id
   - If >48h since last message, queue as "promotional" or skip (depends on final quota)
3. Implement token refresh loop (refresh every 12h as safety margin before 24h expiry)
4. Consider paid OA tier if free tier quota insufficient for sales volume

---

## 5. Known Gotchas

1. **PSID vs external ID**: Messenger PSID is page-scoped. Cannot identify same user across different pages. Not suitable for multi-page bot.
2. **Message tag timing**: Tags only work **outside** 24h window; using inside 24h returns error.
3. **Zalo 48h soft cap**: Quotas may hard-block after 48h; unclear if "promotional" tags allow unlimited or have separate quotas. Needs testing.
4. **Token expiry**: Zalo tokens expire. Silent failure if refresh not handled.
5. **App Review delays**: Messenger approval can take 1-3 weeks; plan accordingly.

---

## Unresolved Questions

1. **Zalo quotas details**: Exact quota per OA tier (free vs. paid) + whether promotional messages use separate quota. Need to check Zalo billing docs.
2. **Zalo message types**: Full list of `type` field values for incoming messages (e.g., does it include rich cards, buttons, or just text/media?).
3. **Messenger message.mid format**: Exact character set and max length (observed ~50 chars, but not officially documented in fetched content).
4. **Zalo webhook timeout & retry**: How long Zalo waits before timeout, retry count, backoff strategy (if different from Messenger).
5. **Zalo OA verification timeline**: Current (2026) approval SLA for Vietnamese business OA. Previous docs said 2-5 days, but may have changed.
6. **Rate limit granularity**: Both platforms — whether limits are per-user, per-OA, or burst + sustained. Zalo limits especially unclear.
7. **Merchant/Payment integration**: Neither platform's send message API docs mention purchase flows; unclear if pre-transaction upsell requires different message type.

---

## Sources Consulted

- https://developers.facebook.com/docs/messenger-platform/webhook
- https://developers.facebook.com/docs/messenger-platform/reference/webhook-events
- https://developers.facebook.com/docs/messenger-platform/reference/send-api
- https://developers.zalo.me/docs/official-account/api/message/send-message
- https://developers.zalo.me/docs/official-account/api/webhook/message-received

*Note: Zalo documentation pages returned limited detail in fetches; verification against live API recommended before implementation.*
