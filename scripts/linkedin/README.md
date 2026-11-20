# LinkedIn posting scripts

Automated weekly LinkedIn posting for the WARN Index company page.

## Files

- `weekly_layoffs.py` — fetches 7-day WARN layoff data from the public
  warnindex.com API; prints JSON matching the schema the scheduled task expects.
- `linkedin_post.py` — posts to the WARN Index LinkedIn organization page via
  the Community Management API. Reads credentials from
  `~/.warnindex/linkedin.json`. Auto-refreshes expired access tokens.
- `linkedin_auth.py` — one-time interactive OAuth 2.0 setup. Creates
  `~/.warnindex/linkedin.json`.

## Setup

1. Create a LinkedIn app at <https://developer.linkedin.com/>.
2. Associate it with the WARN Index LinkedIn page (you must be a page admin).
3. Request the **Community Management API** product.
4. Add `http://localhost:8585/callback` as a redirect URL in the Auth tab.
5. Run the auth helper:
   ```
   python3 linkedin_auth.py
   ```
6. Enter client ID, client secret, and the numeric organization ID when prompted.

## Deployment

These scripts are installed to `~/.warnindex/` and called by the
`weekly-linkedin-layoffs-draft` scheduled task
(`~/.claude/scheduled-tasks/weekly-linkedin-layoffs-draft/`).

```bash
cp scripts/linkedin/*.py ~/.warnindex/
chmod 600 ~/.warnindex/linkedin_post.py ~/.warnindex/linkedin_auth.py
```

## Credentials

`~/.warnindex/linkedin.json` contains OAuth tokens and is **not tracked**.
Access tokens last 60 days; refresh tokens last 365 days. The posting script
auto-refreshes access tokens. After ~1 year, re-run `linkedin_auth.py`.
