set targetSubject to "Job opening found — Dropbox — Senior Infrastructure Security Engineer"
set outLines to {}
tell application "Mail"
  repeat with a in every account
    repeat with m in every mailbox of a
      if name of m is "Sent Mail" or name of m is "Sent Items" or name of m is "Sent" then
        set checkedCount to 0
        repeat with msgRef in messages of m
          set checkedCount to checkedCount + 1
          if checkedCount > 75 then exit repeat
          try
            set subj to subject of msgRef as text
            if subj is targetSubject then
              copy ((name of a as text) & " :: " & (name of m as text) & " :: " & (date sent of msgRef as text) & " :: " & subj) to end of outLines
              exit repeat
            end if
          end try
        end repeat
      end if
    end repeat
  end repeat
end tell
return outLines
