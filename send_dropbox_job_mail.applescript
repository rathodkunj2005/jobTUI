set recipientAddress to "kunj.rathod@utah.edu"
set messageSubject to "Job opening found — Dropbox — Senior Infrastructure Security Engineer"
set messageBody to "Company: Dropbox" & return & ¬
  "Role: Senior Infrastructure Security Engineer" & return & ¬
  "Posting date: 2026-06-11T12:22:23-04:00 (Greenhouse ATS metadata)" & return & ¬
  "URL: https://jobs.dropbox.com/listing/7967465?gh_jid=7967465" & return & ¬
  "Tracker status after update: Watching" & return & return & ¬
  "Why it looks relevant: This is a backend/platform-adjacent infrastructure security role covering AI and agentic infrastructure, model gateways, inference services, vector stores, retrieval systems, and cloud/Kubernetes platforms. Caveat: it is senior/security-heavy and lists 9+ years of security or related industry experience, so it is likely a stretch but newly posted and directly tied to AI infrastructure."

tell application "Mail"
  set newMessage to make new outgoing message with properties {subject:messageSubject, content:messageBody, visible:false}
  tell newMessage
    make new to recipient at end of to recipients with properties {address:recipientAddress}
    send
  end tell
end tell
return "sent"
