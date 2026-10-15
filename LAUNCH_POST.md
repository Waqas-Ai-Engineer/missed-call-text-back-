# Launch kit (optional)

## X / LinkedIn (3 sentences)
Service businesses lose jobs every time a call goes to voicemail. I open-sourced Missed Call Text Back: a zero-dependency Python tool that turns a call log into a smart SMS plan (quiet hours, repeat-caller merging, urgent voicemails first). Try the 2-minute demo: https://github.com/Waqas-Ai-Engineer/missed-call-text-back

## Reddit-style (r/n8n, r/automation, r/Python as fits - check each subreddit's self-promo rules first)
**Title:** I wrote a small open-source missed-call text-back planner (no SaaS, no dependencies) - feedback welcome

Most "text back missed calls" setups just blast a canned message. I wanted something that also: skips people you already called back, merges repeat callers, holds texts during quiet hours but lets urgent voicemails ("burst pipe") through, and says "we reopen Thu 8:00 AM" when you are closed. It reads a CSV call log, prints a table/JSON/CSV plan, and has an optional Twilio webhook (dry-run by default). JSON output drops straight into n8n/Zapier. Demo uses fictional data. Code + tests: https://github.com/Waqas-Ai-Engineer/missed-call-text-back - what industries or providers would you want next?

## Show HN title
Show HN: Missed Call Text Back - zero-dependency Python planner for SMS replies to missed calls
