\## Conversation logging



Rule 0:

After every exchange, append my question and a concise answer to gprun/c/cqa.md if topic is about
China A stock or gprun/c/cqa.md if topic is about USA stock.



Rules:

\- Append only. Never edit or delete existing log content.

\- Record my question verbatim, exactly as I typed it, with no rewording.

\- For the answer, log only the substantive result, not the process. Specifically:

&#x20; - Exclude tool calls, commands run, file reads, search steps, and any

&#x20;   "how I got there" narration.

&#x20; - Exclude intermediate reasoning and status updates.

&#x20; - Include the actual conclusion, recommendation, explanation, or final

&#x20;   answer I would care about.

\- Format each entry as:



&#x20; ## \[YYYY-MM-DD HH:MM]

&#x20; ### Q

&#x20; <my question, verbatim>

&#x20; ### A

&#x20; <clean answer: result or conclusion only, no process>



\- Do this automatically without me asking each time.

\- commit to the file mentioned in Rule 0.



\## Chat output brevity



\- Keep your replies in the chat terminal short. Give the direct answer only:

&#x20; conclusion, recommendation.

\- Omit process narration, restating my question, preamble, and recap.

\- Do not explain how you arrived at the answer unless I ask.

\- The full answer goes in the log file; the chat terminal reply can be a

&#x20; condensed version of it.

keep logged answers tight: key points, decisions, and code/config only — no expansion

