-- keynote_export.applescript — open a .pptx/.key in Keynote and export to PDF.
-- Keynote renders custom CJK fonts correctly (LibreOffice does not), and (unlike
-- sandboxed PowerPoint) its AppleScript export can write to /tmp.
--   osascript keynote_export.applescript <input.pptx|.key> <output.pdf>
-- Run twice: once on the original (with-text bg) and once on text-stripped.pptx
-- (no-text bg). Then render_pdf.swift turns each PDF into per-page PNGs.
on run argv
	set inPath to item 1 of argv
	set outPath to item 2 of argv
	tell application "Keynote"
		activate
		set doc to open POSIX file inPath
		delay 6
		export doc to POSIX file outPath as PDF
		close doc saving no
		return "exported " & outPath
	end tell
end run
