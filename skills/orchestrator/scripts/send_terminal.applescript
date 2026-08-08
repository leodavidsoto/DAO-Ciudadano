on run argv
    set windowName to item 1 of argv
    set filePath to item 2 of argv
    
    set commandText to read POSIX file filePath as «class utf8»
    set the clipboard to commandText
    
    tell application "Terminal"
        activate
        set targetWindow to null
        repeat with w in windows
            if name of w contains windowName then
                set targetWindow to w
                set index of w to 1
                exit repeat
            end if
        end repeat
    end tell
    
    if targetWindow is not null then
        delay 0.5
        tell application "System Events"
            tell process "Terminal"
                set frontmost to true
                keystroke "v" using command down
                delay 0.5
                keystroke return
            end tell
        end tell
        return "Command pasted and sent to " & windowName
    else
        return "Window not found: " & windowName
    end if
end run
