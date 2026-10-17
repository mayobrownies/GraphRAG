## What this changes

## SRS / SDD requirements covered
<!-- e.g. 3.4.6 duplicate upload, SDD 5.4 job locking -->

## Checklist
- [ ] Tests added or updated (`pytest`, `npm test`)
- [ ] New queries only return the signed-in user's documents and the global corpus (SRS 4.1.4)
- [ ] No secrets or `.env` values in the diff
- [ ] New environment variables added to `.env.example` and `render.yaml`
- [ ] If `graph_schema.py` or `supabase/schema.sql` changed: noted above, and `GraphView.jsx` colors / Supabase SQL updated
