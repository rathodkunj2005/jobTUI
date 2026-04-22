set targetSubject to "Job opening found — MongoDB — Software Engineer 3"
tell application "Mail"
  set foundLines to {}
  repeat with a in every account
    repeat with m in every mailbox of a
      set mname to ""
      try
        set mname to name of m as text
      end try
      if mname is "Sent Mail" or mname is "Sent Items" then
        repeat with msgRef in (messages of m)
          try
            set subj to subject of msgRef as text
          on error
            set subj to ""
          end try
          if subj is targetSubject then
            try
              set d to date sent of msgRef as text
            on error
              set d to ""
            end try
            copy ((name of a as text) & " || " & mname & " || " & d & " || " & subj) to end of foundLines
            exit repeat
          end if
        end repeat
      end if
    end repeat
  end repeat
  return foundLines
end tell