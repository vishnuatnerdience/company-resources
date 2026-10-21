# Nerdience Resources (front door)

The single entry point to the Company Knowledge Portal. People open this site,
sign in once with their work email, and choose a department site.

| Page | Path | Protected? |
| --- | --- | --- |
| Landing: "Sign in with your work email" | `/` | No (public; contains no internal information) |
| Choose a department (General, Engineering, Management) + popular pages | `/home/` | Yes, Cloudflare Access app **Resources home** |
| No access to a department site | `/no-access/?portal=<department>` | No (public, so a denied person can always reach it) |

Live address (demo): `https://nerdience-resources.pages.dev/`.
Target address (production): `https://resources.nerdience.com/` (implementation plan §2).

## How sign-in works

1. The **Sign in** button links to `/home/`. Cloudflare Access protects `/home/`,
   so it shows the Nerdience-branded login page (email + one-time code).
2. After sign-in, `/home/` shows the signed-in email, the department sites and
   a few popular pages.
3. Cloudflare remembers the sign-in for every Access application, so opening a
   department site from here does not ask for a code again.
4. A department site the person may not open redirects to this site's
   `/no-access/?portal=<department>` (set by `scripts/sync_access.py` in
   `company-docs`).

Who may open which department is defined in `departments.yml` in `company-docs`;
group membership lives in the Cloudflare dashboard, not in any repository.

## Sign-in flow

1. **Sign in** opens `/home/` (protected), which sends the person straight to
   the first portal in `login_order` (`kit/portals.yml`): Engineering, then
   HR & General.
2. If Cloudflare Access denies them, the portal's deny URL is
   `/home/next/?from=<portal>`, which tries the next portal (only during the
   2 minutes after sign-in), and finally shows `/no-access/`.
3. People with access to several portals land in the first and switch from
   the top bar; `/home/?choose` shows every portal.

No email addresses or group lists are needed for this: Cloudflare Access
decides, the front door only follows its answers.

## Portal kit (`kit/`)

Shared by both content repositories, so they never drift:

| Path | What |
| --- | --- |
| `kit/portals.yml` | the ONE file: sites, folder → site mapping, audiences, sign-in order |
| `kit/theme/` | look of every portal site |
| `kit/scripts/` | validate, generate (menus, sections, related docs), build, Cloudflare sync, smoke test, front-door renderer |
| `kit/templates/` | `template.md`, `example.md` (downloads) and the in-portal template page |
| `kit/workflows/` | the PR and deploy workflows copied into each content repository |
| `kit/tests/` | unit tests (run in this repository's CI) |

After changing `kit/portals.yml` or `kit/templates/`, run
`python kit/scripts/render_front_door.py` (CI fails if you forget).

## Design

Same design language as the department sites (black bar with a yellow
underline, icon tiles, rounded cards). Responsive: phone (< 40rem), tablet
(< 64rem), desktop. Follows the device's light/dark setting; the landing page
is always dark. Keyboard focus is always visible and motion is reduced when the
device asks for it.

## Files

```text
public/                 the website, published as-is (no build step)
  index.html            landing page
  home/index.html       choose a department (protected)
  no-access/index.html  no access to a department (public)
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

Department addresses are written in `public/home/index.html` and must match
`departments.yml` in `company-docs`. When a department is added there, add its
card here and its host to `PORTAL_HOSTS` in `scripts/check_site.py`.
