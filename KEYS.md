# Environment variables (names only)

Values go only into `.env` in the repository root (`chmod 600`, ignored by git). This file
lists the names the code reads; it never holds a value.

## Meta: Facebook Page and Instagram (`kotleta` profile)

| Variable | Purpose |
|---|---|
| `FB_PAGE_KOTLETA_ID` | Facebook Page id |
| `FB_PAGE_KOTLETA_TOKEN` | Page access token (also used for the linked Instagram account) |
| `IG_KOTLETA_USER_ID` | Instagram business account id linked to the Page |
| `META_GRAPH_VERSION` | optional, Graph API version (default `v27.0`) |

Any other Page works the same way: `FB_PAGE_<NAME>_ID`, `FB_PAGE_<NAME>_TOKEN` and, for
Instagram, `IG_<NAME>_USER_ID` give the targets `fb:<name>` and `ig:<name>`.

## LinkedIn (personal profile)

| Variable | Purpose |
|---|---|
| `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET` | developer app credentials, used by `login linkedin` |
| `LINKEDIN_ACCESS_TOKEN`, `LINKEDIN_TOKEN_EXPIRES_AT`, `LINKEDIN_PERSON_URN` | written by `login linkedin` |
| `LINKEDIN_API_VERSION` | optional (default `202610`) |

## X (API v2, OAuth 1.0a user context)

| Variable | Purpose |
|---|---|
| `X_API_KEY`, `X_API_SECRET` | consumer key and secret |
| `X_ACCESS_TOKEN`, `X_ACCESS_SECRET` | user access token and secret |
| `X_MONTHLY_CAP_USD` | optional, monthly spending cap (default `5.00`) |
| `X_PRICE_POST`, `X_PRICE_POST_WITH_URL`, `X_PRICE_POST_WITH_MEDIA`, `X_PRICE_MEDIA_UPLOAD` | optional, prices used by the local budget ledger |

## AI (panel)

| Variable | Purpose |
|---|---|
| `GEMINI_API_KEY` | Gemini Interactions API: topics, per-network texts and voice transcription |
| `AI_MONTHLY_CAP_USD` | optional, shared monthly AI spending cap (default `10.00`) |

## Poster and factory paths (process environment, not secrets)

`MF_ENV_FILE` (another env file), `MF_STATE_DIR` (poster state folder), `MF_IMAGE_LIBRARY`
(image library), `MF_CONTENT_DIR` (factory content folder holding `stock/` and `rules.json`),
`MF_FACTORY_STATE_DIR` (factory state folder).
