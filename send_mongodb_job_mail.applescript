set theSubject to "Job opening found — MongoDB — Software Engineer 3"
set theBody to "Company: MongoDB
Role: Software Engineer 3
Posting date: 2026-04-10 (Greenhouse metadata)
URL: https://www.mongodb.com/careers/jobs/7779598
Tracker status: Watching

Why it looks like a good fit:
It matches Kunj's backend/data-infra target closely: the Atlas Backup team is building large-scale distributed backend systems and explicitly calls out Linux, performance, and distributed-systems work.

The live MongoDB job page loaded successfully, and Greenhouse metadata lists Employment Type as Full-time."

tell application "Mail"
  set newMessage to make new outgoing message with properties {subject:theSubject, content:theBody, visible:false}
  tell newMessage
    make new to recipient at end of to recipients with properties {address:"kunj.rathod@utah.edu"}
    send
  end tell
end tell