# Phase 7 — File / URL / Flag Publishing

## What changed

Phase 7 connects the Phase 6 DM workflow's `READY` state to actual Telegram publishing.

- `/uploadconfig` publishes a metadata message containing caption + description.
- URL resources use a Telegram URL button; the raw URL is not printed in the group message.
- File resources use a Telegram callback download button. The file is delivered to the clicking user via its Telegram `file_id`; the bot token is never exposed in a URL.
- Forum custom topics publish with `message_thread_id`; General topic uses Telegram's default thread behavior.
- `/uploadflag` publishes the image with copy-friendly Main-Flag/Sub-Flags and a separate description message in the same topic.
- Published metadata is persisted in `ghostea_resources` for the dashboard and future management features.
- READY -> PUBLISHING is claimed with a conditional database update to prevent duplicate confirmation clicks.
- Closed topics are allowed for upload publishing: if the bot has `can_manage_topics`, Ghostea reopens the closed topic immediately before publishing, then sends the content.
- Hidden General and deleted/inactive topics remain hard rejects.
- Telegram itself returns `TOPIC_CLOSED` for direct sends to a closed topic, so Ghostea does not pretend there is a separate "post while closed" permission; it uses the bot's `can_manage_topics` permission to reopen first.
- The workflow's admin/topic revalidation runs immediately before Telegram publishing.

## Supabase

Run the Phase 7 additive SQL once. Do not drop or recreate existing tables.

## Deployment

- database.sql: **YES**, only the new Phase 7 section
- Render: **YES**, redeploy
- Vercel: **NO**, unless dashboard source is separately changed
- UptimeRobot: **NO**, keep the existing health monitor

## Telegram test

Use a disposable test group first.

1. `/uploadconfig` -> normal group -> File -> caption -> description -> Upload.
2. Confirm only the metadata message is visible; the original file is not posted directly.
3. Click Download and confirm the file is delivered in the clicker's DM.
4. Repeat with URL and confirm the group message has only the Open/Download button, not the raw URL.
5. Repeat in a forum custom topic and verify the post stays in that topic.
6. Repeat in General and verify it does not force a custom thread.
7. `/uploadflag` -> image -> Main-Flag -> Sub-Flags -> description -> Upload.
8. Close the selected topic before confirmation and verify Ghostea reopens it (when the bot has Manage Topics) and publishes successfully.
9. Hide General or delete the selected topic before confirmation and verify publishing is rejected.
10. Remove the requester's admin rights before confirmation and verify publishing is rejected.
11. Double-tap Upload and verify only one publication is created.
