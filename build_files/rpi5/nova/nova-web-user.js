// nova-web Firefox profile (pages Nova opens). Copied into the profile's user.js by
// novad on every launch. Raspberry Pi 5 image only.
// Video: H.264/H.265/AAC come from RPM Fusion's libavcodec-freeworld through Firefox's
// ffmpeg path; no Cisco OpenH264 download.
user_pref("media.ffmpeg.enabled", true);
user_pref("media.gmp-gmpopenh264.enabled", false);
user_pref("media.gmp-gmpopenh264.autoupdate", false);
user_pref("media.autoplay.default", 0);
user_pref("media.autoplay.blocking_policy", 0);
// Faster start: no session restore, no first-run/what's-new pages, no default-browser check.
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("browser.startup.page", 0);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("startup.homepage_welcome_url", "");
user_pref("startup.homepage_welcome_url.additional", "");
user_pref("browser.aboutwelcome.enabled", false);
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("trailhead.firstrun.didSeeAboutWelcome", true);
user_pref("browser.newtabpage.enabled", false);
user_pref("browser.newtabpage.activity-stream.feeds.topsites", false);
user_pref("browser.newtabpage.activity-stream.feeds.section.topstories", false);
user_pref("extensions.pocket.enabled", false);
user_pref("browser.discovery.enabled", false);
user_pref("extensions.getAddons.showPane", false);
user_pref("extensions.htmlaboutaddons.recommendations.enabled", false);
// No background network work at start.
user_pref("app.update.auto", false);
user_pref("app.normandy.enabled", false);
user_pref("app.shield.optoutstudies.enabled", false);
user_pref("datareporting.healthreport.uploadEnabled", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("toolkit.telemetry.enabled", false);
user_pref("toolkit.telemetry.unified", false);
user_pref("toolkit.telemetry.archive.enabled", false);
user_pref("browser.ping-centre.telemetry", false);
user_pref("browser.safebrowsing.downloads.remote.enabled", false);
user_pref("network.connectivity-service.enabled", false);
user_pref("browser.region.update.enabled", false);
user_pref("extensions.systemAddon.update.enabled", false);
// Page loads: speculative connects and DNS prefetch on; HTTP/3 on.
user_pref("network.http.speculative-parallel-limit", 6);
user_pref("network.dns.disablePrefetch", false);
user_pref("network.predictor.enabled", true);
user_pref("network.http.http3.enable", true);
// Rendering on the Pi's GPU through WebRender; fewer content processes for 8 GB or less.
user_pref("gfx.webrender.all", true);
user_pref("dom.ipc.processCount", 4);
user_pref("browser.cache.memory.capacity", 262144);
