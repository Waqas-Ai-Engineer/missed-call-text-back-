# SMS compliance notes (not legal advice)

Texting people is regulated (for example TCPA and carrier registration such as A2P 10DLC in the US; similar rules elsewhere).

- A caller who phones you is generally expected to receive a reply about their call, but get advice for your country and industry.
- Keep the opt-out line (`append_opt_out`) and honour STOP replies; add those numbers to `do_not_text`.
- Do not include sensitive details (health, payments) in texts.
- Register your sending number/brand with your SMS provider where required.
- Review `templates.py` wording with your own legal counsel before real use.
