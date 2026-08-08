tell application "Terminal"
	set output to ""
	repeat with w in windows
		repeat with t in tabs of w
			set output to output & "--- Window: " & name of w & " ---" & return & history of t & return
		end repeat
	end repeat
	return output
end tell
