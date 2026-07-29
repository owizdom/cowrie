# CowriePay — Android package

## Is this a second app?

No. There is one application — the PWA in `surfaces/` — and this directory is a
**packaging recipe**, not another copy of it.

A Trusted Web Activity is a native shell containing no application code: it
opens `https://cowrie-web-production.up.railway.app/pay` full-screen with no
browser chrome. The screens, the logic and the API calls are the same ones the
browser runs, served from the same deployment. Wrapping it this way is what
Google Play itself recommends for a web-first app, and it is the only route onto
the Play Store for one.

So the two are not alternatives to each other:

| | What it is | What it needs |
|---|---|---|
| `surfaces/` | The application | — |
| `android/` | A Play Store wrapper around it | A deployed HTTPS host, `bubblewrap`, a signing key |

If Play distribution is not wanted, this directory can be deleted without
affecting anything: Android Chrome already installs the PWA to the home screen
from the site itself, which produces the same standalone app with the same icon.
SRS §2.5 constraint 3 authorises the PWA as the shipped form for this build, so
nothing here is required — it is the on-ramp to Play, kept because the SRS names
Android 8.0+ as a target.

## Build the APK

```bash
npm install -g @bubblewrap/cli
cd android
bubblewrap init --manifest https://cowrie-web-production.up.railway.app/manifest.webmanifest
bubblewrap build
```

Output: `app-release-signed.apk`.

`twa-manifest.json` already points at the deployed host, so `bubblewrap` has
everything it needs except a signing key, which it will offer to generate.
**No APK is checked in and none has been built** — this is the recipe, not the
artefact.

## One prerequisite that cannot be skipped

A TWA opens **without a browser address bar only if** Android can verify that
the app and the website belong to the same owner. That check is Digital Asset
Links, and it needs two things:

1. the site served over **HTTPS on a real domain** — `localhost` will not do;
2. `/.well-known/assetlinks.json` on that domain, containing the SHA-256
   fingerprint of the key the APK was signed with.

`bubblewrap build` prints the fingerprint. Put the file it generates at
`surfaces/public/.well-known/assetlinks.json` and redeploy before installing
the APK.

The host is deployed, so step 1 is satisfied. Step 2 is not: no key has been
generated, so no fingerprint exists and no `assetlinks.json` is published. Until
that is done a sideloaded APK would open with an address bar visible, which is
the TWA failing to verify rather than the app working.

## Installing without an APK

On Android Chrome the app installs directly from the site: open `/pay` and
either accept the install prompt or use ⋮ → *Install app*. That produces a real
home-screen app with its own icon and no browser chrome — the same result the
APK gives, without Play distribution.

On iOS, Safari installs it through Share → *Add to Home Screen*.
