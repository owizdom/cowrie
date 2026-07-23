# CowriePay — Android package

CowriePay is a PWA. On Android it can be wrapped as a **Trusted Web Activity**
(TWA) and installed as a normal `.apk`, which is what Google Play itself
recommends for a web-first app.

## Build the APK

```bash
npm install -g @bubblewrap/cli
cd android
bubblewrap init --manifest https://<your-host>/manifest.webmanifest
bubblewrap build
```

Output: `app-release-signed.apk`.

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

Without the deployed HTTPS host there is no fingerprint to bind to, so the APK
cannot be produced yet — deploy first, then run the two commands above.

## Installing without an APK

On Android Chrome the app installs directly from the site: open `/pay` and
either accept the install prompt or use ⋮ → *Install app*. That produces a real
home-screen app with its own icon and no browser chrome — the same result the
APK gives, without Play distribution.

On iOS, Safari installs it through Share → *Add to Home Screen*.
