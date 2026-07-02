set recipientAddress to "kunj.rathod@utah.edu"
set theSubject to "Job opening found — Datadog — Senior Software Engineer - Observability Visibility"
set theBody to "Company: Datadog
Role: Senior Software Engineer - Observability Visibility
Posting date: 2026-06-12 (Greenhouse ATS metadata first_published=2026-06-12T09:30:31-04:00)
URL: https://careers.datadoghq.com/detail/8001760/?gh_jid=8001760
Tracker status after update: Watching

Why it looks like a good fit: This is a backend/platform/SRE tooling role focused on observability and resilience baselines, automation, service-owner tooling, Go/Python, and scalable production systems. It also explicitly mentions AI-enabled software features, which lines up well with your Microsoft Fabric + AI infrastructure story, though it has a 5+ YOE seniority caveat.

Tracker update recorded Date Found = 2026-06-12 and appended the posting details to the Datadog row."

tell application "Mail"
    set newMessage to make new outgoing message with properties {subject:theSubject, content:theBody, visible:false}
    tell newMessage
        make new to recipient at end of to recipients with properties {address:recipientAddress}
        send
    end tell
end tell
