# Nerdience Resources (front door)

The single entry point to the Company Knowledge Portal. People open this site,
sign in once with their work email, and choose a portal.

| Page | Path | Protected? |
| --- | --- | --- |
| Landing: "Sign in with your work email" | `/` | No (public; contains no internal information) |
| Choose a portal (Engineering, HR & General) | `/home/` | Yes, Cloudflare Access app **Resources home** |
| No access to a whole portal | `/no-access/` | No (public, so a denied person can always reach it) |

Live address (demo): `https://nerdience-resources.pages.dev/`.
Target address (production): `https://resources.nerdience.com/` (implementation plan §2).

## How sign-in works

1. The **Sign in** button links to `/home/`. Cloudflare Access protects `/home/`,
   so it shows the Nerdience-branded login page (email + one-time code).
2. After sign-in, `/home/` shows the signed-in email and the two portals.
3. Cloudflare remembers the sign-in for every Access application, so opening a
   portal from here does not ask for a code again.
4. Inside a portal, sections the person may not open redirect to that portal's
   `/no-access/` page. A portal the person may not open at all redirects to this
   site's `/no-access/?portal=engineering` (or `hr`).

Access configuration lives in the Cloudflare dashboard, not in this repository.
See `docs/security/portal-access-control.md` in `company-engineering`.

## Files

```text
public/                 the website, published as-is (no build step)
  index.html            landing page
  home/index.html       choose a portal (protected)
  no-access/index.html  no access to a portal (public)
  assets/               stylesheet, logo, favicon
  robots.txt, _headers  keep search engines out; security headers
scripts/check_site.py   site checks run in CI
scripts/review_gate.py  review gate (same as the portal repositories)
.github/workflows/      pr-checks.yml (CI) and deploy.yml (CD)
```

## Changing the site

Work on a branch and open a pull request, exactly as in the portal
repositories. Checks run automatically; after approval and merge the site is
deployed to Cloudflare Pages.

Run the checks locally before pushing:

```bash
pip install "pathspec==0.12.1" "PyYAML==6.0.2"
python scripts/check_site.py
python scripts/review_gate.py --lint
npx --yes html-validate@9.5.5 "public/**/*.html"
```

Portal addresses are written in `public/home/index.html`. Update them there when
the portals move to `resources.nerdience.com`.
