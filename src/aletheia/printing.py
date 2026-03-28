"""Windows printer integration.

Uses PowerShell commands to list printers and print text files
on native Windows.
"""

import base64
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _ps_escape(value: str) -> str:
    """Escape a string for safe use inside a PowerShell double-quoted string."""
    return value.replace('`', '``').replace('"', '`"').replace('$', '`$')


def list_windows_printers() -> list[str]:
    """Return a list of available Windows printer names via PowerShell Get-Printer."""
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-Printer | Select-Object -ExpandProperty Name",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            logger.warning("Get-Printer failed: %s", result.stderr.strip())
            return []
        names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return names
    except FileNotFoundError:
        logger.warning("powershell not found")
        return []
    except subprocess.TimeoutExpired:
        logger.warning("Get-Printer timed out")
        return []
    except Exception as e:
        logger.warning("Failed to list printers: %s", e)
        return []


def list_windows_fonts() -> list[str]:
    """Return a list of installed font family names via .NET."""
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8;"
                " Add-Type -AssemblyName System.Drawing;"
                " (New-Object System.Drawing.Text.InstalledFontCollection)"
                ".Families | ForEach-Object { $_.Name }",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            logger.warning("Font list failed: %s", result.stderr.strip())
            return []
        names = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        return names
    except FileNotFoundError:
        logger.warning("powershell not found")
        return []
    except subprocess.TimeoutExpired:
        logger.warning("Font list timed out")
        return []
    except Exception as e:
        logger.warning("Failed to list fonts: %s", e)
        return []


PAPER_SIZES = [
    "A3",
    "A4",
    "A5",
    "A6",
    "Letter",
    "Legal",
    "B4 (JIS)",
    "B5 (JIS)",
]

# Paper dimensions in 1/100 inch (width x height, portrait)
PAPER_DIMENSIONS = {
    "A3": (1169, 1654),
    "A4": (827, 1169),
    "A5": (583, 827),
    "A6": (413, 583),
    "Letter": (850, 1100),
    "Legal": (850, 1400),
    "B4 (JIS)": (1012, 1433),
    "B5 (JIS)": (717, 1012),
}


def print_text(
    text: str,
    printer_name: str,
    paper_size: str = "",
    landscape: bool = False,
    font_size: int = 12,
    font_name: str = "Malgun Gothic",
    margin_lr: int = 60,
) -> bool:
    """Print text content to the specified Windows printer.

    Uses .NET ``System.Drawing.Printing.PrintDocument`` via PowerShell to
    render text with configurable orientation and font size.

    Returns True on success, False on failure. Never raises.
    """
    if not text or not text.strip():
        logger.warning("Print skipped – empty text")
        return False

    try:
        # Encode text as Base64 UTF-8 to pass safely to PowerShell
        text_b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")

        landscape_str = "$true" if landscape else "$false"

        # Build PowerShell script using .NET PrintDocument
        ps_script = f'''
Add-Type -AssemblyName System.Drawing

$textB64    = "{text_b64}"
$printerName = "{_ps_escape(printer_name)}"
$paperSize  = "{_ps_escape(paper_size)}"
$landscape  = {landscape_str}
$fontSize   = {font_size}
$marginLR   = {margin_lr}

$textBytes = [System.Convert]::FromBase64String($textB64)
$textContent = [System.Text.Encoding]::UTF8.GetString($textBytes)
$lines = $textContent -split "`n"

$doc = New-Object System.Drawing.Printing.PrintDocument
$doc.PrinterSettings.PrinterName = $printerName
$doc.DefaultPageSettings.Landscape = $landscape

# Set paper size if specified
if ($paperSize -ne "") {{
    foreach ($ps in $doc.PrinterSettings.PaperSizes) {{
        if ($ps.PaperName -eq $paperSize) {{
            $doc.DefaultPageSettings.PaperSize = $ps
            break
        }}
    }}
}}

# Set margins (unit: 1/100 inch)
$doc.DefaultPageSettings.Margins = New-Object System.Drawing.Printing.Margins($marginLR, $marginLR, 30, 30)
$doc.OriginAtMargins = $true

# Create font with style fallback for variable/non-standard fonts
$fontName = "{_ps_escape(font_name)}"
try {{
    $fontFamily = New-Object System.Drawing.FontFamily($fontName)
    $style = [System.Drawing.FontStyle]::Regular
    if (-not $fontFamily.IsStyleAvailable($style)) {{
        if ($fontFamily.IsStyleAvailable([System.Drawing.FontStyle]::Bold)) {{
            $style = [System.Drawing.FontStyle]::Bold
        }} elseif ($fontFamily.IsStyleAvailable([System.Drawing.FontStyle]::Italic)) {{
            $style = [System.Drawing.FontStyle]::Italic
        }}
    }}
    $font = New-Object System.Drawing.Font($fontFamily, $fontSize, $style)
}} catch {{
    $font = New-Object System.Drawing.Font("Malgun Gothic", $fontSize)
}}
# GenericTypographic for accurate word-wrap measurement
$measureFmt = [System.Drawing.StringFormat]::GenericTypographic.Clone()
$measureFmt.FormatFlags = [System.Drawing.StringFormatFlags]::NoWrap

# Center-alignment format for drawing (GDI+ handles centering internally)
$centerFmt = [System.Drawing.StringFormat]::GenericTypographic.Clone()
$centerFmt.Alignment = [System.Drawing.StringAlignment]::Center
$centerFmt.FormatFlags = [System.Drawing.StringFormatFlags]::NoWrap

# --- Word-wrap: break original lines into wrapped lines at word boundaries ---
# Use 100 DPI so 1 pixel = 1/100 inch, matching PaperSize/Margin units
$tempBmp = New-Object System.Drawing.Bitmap(1,1)
$tempBmp.SetResolution(100, 100)
$tempGfx = [System.Drawing.Graphics]::FromImage($tempBmp)
# Printable width from page settings (unit: 1/100 inch)
$ps = $doc.DefaultPageSettings
if ($landscape) {{
    $pw = $ps.PaperSize.Height - $ps.Margins.Left - $ps.Margins.Right
}} else {{
    $pw = $ps.PaperSize.Width - $ps.Margins.Left - $ps.Margins.Right
}}
if ($pw -lt 50) {{ $pw = 300 }}
$maxWidth = [float]$pw

function WrapLine($text, $gfx, $fnt, $maxW) {{
    if ([string]::IsNullOrEmpty($text)) {{ return @("") }}

    # If the whole line fits, return as-is
    $sz = $gfx.MeasureString($text, $fnt, [int]::MaxValue, $measureFmt)
    if ($sz.Width -le $maxW) {{ return @($text) }}

    # Balanced wrapping: distribute text evenly across lines
    $numLines = [Math]::Ceiling($sz.Width / $maxW)
    $targetW = [Math]::Min($maxW, $sz.Width / $numLines * 1.05)

    $result = [System.Collections.Generic.List[string]]::new()
    # Split by spaces (works for Korean phrases separated by spaces & English words)
    $tokens = $text -split '(?<= )'  # split keeping trailing space with each token
    $current = ""

    foreach ($token in $tokens) {{
        $test = $current + $token
        $tsz = $gfx.MeasureString($test, $fnt, [int]::MaxValue, $measureFmt)
        if ($tsz.Width -le $targetW -or $current -eq "") {{
            $current = $test
        }} else {{
            $result.Add($current.TrimEnd())
            $current = $token
        }}
        # If a single token is wider than maxW, break it char by char
        $csz = $gfx.MeasureString($current, $fnt, [int]::MaxValue, $measureFmt)
        if ($csz.Width -gt $maxW -and $current.Length -gt 1) {{
            $chars = $current.ToCharArray()
            $buf = ""
            foreach ($ch in $chars) {{
                $try = $buf + $ch
                $chsz = $gfx.MeasureString($try, $fnt, [int]::MaxValue, $measureFmt)
                if ($chsz.Width -gt $maxW -and $buf -ne "") {{
                    $result.Add($buf)
                    $buf = [string]$ch
                }} else {{
                    $buf = $try
                }}
            }}
            $current = $buf
        }}
    }}
    if ($current -ne "") {{ $result.Add($current.TrimEnd()) }}
    return $result.ToArray()
}}

$wrappedLines = [System.Collections.Generic.List[string]]::new()
foreach ($rawLine in $lines) {{
    if ($rawLine -eq $null) {{ $rawLine = "" }}
    $wl = WrapLine $rawLine $tempGfx $font $maxWidth
    foreach ($w in $wl) {{ $wrappedLines.Add($w) }}
}}
$tempGfx.Dispose()
$tempBmp.Dispose()

# Pre-measure each wrapped line height
$lineHeights = [System.Collections.Generic.List[float]]::new()
$tempBmp2 = New-Object System.Drawing.Bitmap(1,1)
$tempBmp2.SetResolution(100, 100)
$tempGfx2 = [System.Drawing.Graphics]::FromImage($tempBmp2)
$singleH = $font.GetHeight($tempGfx2)
foreach ($wl in $wrappedLines) {{
    $lineHeights.Add($singleH)
}}
$tempGfx2.Dispose()
$tempBmp2.Dispose()

$script:lineIndex = 0

$doc.add_PrintPage({{
    param($sender, $e)

    $bounds = $e.MarginBounds
    $pageHeight = $bounds.Height

    # Vertical centering: offset if all remaining content fits on this page
    $remainHeight = [float]0
    for ($i = $script:lineIndex; $i -lt $wrappedLines.Count; $i++) {{
        $remainHeight += $lineHeights[$i]
    }}
    if ($remainHeight -le $pageHeight) {{
        $yPos = [float](($pageHeight - $remainHeight) / 2)
    }} else {{
        $yPos = [float]0
    }}

    while ($script:lineIndex -lt $wrappedLines.Count) {{
        $line = $wrappedLines[$script:lineIndex]
        $lineHeight = $lineHeights[$script:lineIndex]

        if (($yPos + $lineHeight) -gt $pageHeight) {{
            $e.HasMorePages = $true
            return
        }}

        # Center-aligned drawing via StringFormat (no manual MeasureString)
        $lineRect = New-Object System.Drawing.RectangleF(0, $yPos, [float]$bounds.Width, $lineHeight)
        $e.Graphics.DrawString($line, $font, [System.Drawing.Brushes]::Black, $lineRect, $centerFmt)

        $yPos += $lineHeight
        $script:lineIndex++
    }}

    $e.HasMorePages = $false
}})

$doc.Print()
$centerFmt.Dispose()
$measureFmt.Dispose()
$font.Dispose()
$doc.Dispose()
'''

        # Encode script as Base64 UTF-16LE for -EncodedCommand
        # This avoids encoding issues with Korean/special chars in font names, paths, etc.
        encoded_cmd = base64.b64encode(ps_script.encode("utf-16-le")).decode("ascii")

        ps_result = subprocess.run(
            ["powershell", "-NoProfile", "-EncodedCommand", encoded_cmd],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if ps_result.returncode != 0:
            logger.warning("PrintDocument failed: %s", ps_result.stderr.strip())
            return False

        logger.info("Printed to %s (landscape=%s, font=%d)", printer_name, landscape, font_size)
        return True

    except FileNotFoundError:
        logger.warning("powershell not found")
        return False
    except subprocess.TimeoutExpired:
        logger.warning("Print command timed out")
        return False
    except Exception as e:
        logger.warning("Print failed: %s", e)
        return False


def print_positioned_text(
    input_text: str,
    output_text: str,
    printer_name: str,
    paper_size: str = "",
    landscape: bool = False,
    font_size: int = 12,
    font_name: str = "Malgun Gothic",
    input_y_pct: float = 10.0,
    output_y_pct: float = 55.0,
    draw_separator: bool = True,
    margin_lr: int = 60,
) -> bool:
    """Print input and output text at specified Y positions on the page.

    Positions are percentages (0-100) of the printable area height.
    X-axis remains horizontally centred. Each block is word-wrapped independently.

    Returns True on success, False on failure.  Never raises.
    """
    if not (input_text or "").strip() and not (output_text or "").strip():
        logger.warning("Print skipped – both texts empty")
        return False

    try:
        input_b64 = base64.b64encode((input_text or "").encode("utf-8")).decode("ascii")
        output_b64 = base64.b64encode((output_text or "").encode("utf-8")).decode("ascii")

        landscape_str = "$true" if landscape else "$false"
        separator_str = "$true" if draw_separator else "$false"

        ps_script = f'''
Add-Type -AssemblyName System.Drawing

$inputB64    = "{input_b64}"
$outputB64   = "{output_b64}"
$printerName = "{_ps_escape(printer_name)}"
$paperSize   = "{_ps_escape(paper_size)}"
$landscape   = {landscape_str}
$fontSize    = {font_size}
$inputYPct   = {input_y_pct}
$outputYPct  = {output_y_pct}
$drawSep     = {separator_str}
$marginLR    = {margin_lr}

$inputBytes  = [System.Convert]::FromBase64String($inputB64)
$inputText   = [System.Text.Encoding]::UTF8.GetString($inputBytes)
$outputBytes = [System.Convert]::FromBase64String($outputB64)
$outputText  = [System.Text.Encoding]::UTF8.GetString($outputBytes)

$inputLines  = if ($inputText)  {{ $inputText  -split "`n" }} else {{ @() }}
$outputLines = if ($outputText) {{ $outputText -split "`n" }} else {{ @() }}

$doc = New-Object System.Drawing.Printing.PrintDocument
$doc.PrinterSettings.PrinterName = $printerName
$doc.DefaultPageSettings.Landscape = $landscape

if ($paperSize -ne "") {{
    foreach ($ps in $doc.PrinterSettings.PaperSizes) {{
        if ($ps.PaperName -eq $paperSize) {{
            $doc.DefaultPageSettings.PaperSize = $ps
            break
        }}
    }}
}}

$doc.DefaultPageSettings.Margins = New-Object System.Drawing.Printing.Margins($marginLR, $marginLR, 30, 30)
$doc.OriginAtMargins = $true

$fontName = "{_ps_escape(font_name)}"
try {{
    $fontFamily = New-Object System.Drawing.FontFamily($fontName)
    $style = [System.Drawing.FontStyle]::Regular
    if (-not $fontFamily.IsStyleAvailable($style)) {{
        if ($fontFamily.IsStyleAvailable([System.Drawing.FontStyle]::Bold)) {{
            $style = [System.Drawing.FontStyle]::Bold
        }} elseif ($fontFamily.IsStyleAvailable([System.Drawing.FontStyle]::Italic)) {{
            $style = [System.Drawing.FontStyle]::Italic
        }}
    }}
    $font = New-Object System.Drawing.Font($fontFamily, $fontSize, $style)
}} catch {{
    $font = New-Object System.Drawing.Font("Malgun Gothic", $fontSize)
}}

# GenericTypographic for accurate word-wrap measurement
$measureFmt = [System.Drawing.StringFormat]::GenericTypographic.Clone()
$measureFmt.FormatFlags = [System.Drawing.StringFormatFlags]::NoWrap

# Center-alignment format for drawing (GDI+ handles centering internally)
$centerFmt = [System.Drawing.StringFormat]::GenericTypographic.Clone()
$centerFmt.Alignment = [System.Drawing.StringAlignment]::Center
$centerFmt.FormatFlags = [System.Drawing.StringFormatFlags]::NoWrap

# --- Word-wrap helper (same as print_text) ---
$tempBmp = New-Object System.Drawing.Bitmap(1,1)
$tempBmp.SetResolution(100, 100)
$tempGfx = [System.Drawing.Graphics]::FromImage($tempBmp)
$pgs = $doc.DefaultPageSettings
if ($landscape) {{
    $pw = $pgs.PaperSize.Height - $pgs.Margins.Left - $pgs.Margins.Right
}} else {{
    $pw = $pgs.PaperSize.Width - $pgs.Margins.Left - $pgs.Margins.Right
}}
if ($pw -lt 50) {{ $pw = 300 }}
$maxWidth = [float]$pw

function WrapLine($text, $gfx, $fnt, $maxW) {{
    if ([string]::IsNullOrEmpty($text)) {{ return @("") }}
    $sz = $gfx.MeasureString($text, $fnt, [int]::MaxValue, $measureFmt)
    if ($sz.Width -le $maxW) {{ return @($text) }}

    # Balanced wrapping: distribute text evenly across lines
    $numLines = [Math]::Ceiling($sz.Width / $maxW)
    $targetW = [Math]::Min($maxW, $sz.Width / $numLines * 1.05)

    $result = [System.Collections.Generic.List[string]]::new()
    $tokens = $text -split '(?<= )'
    $current = ""
    foreach ($token in $tokens) {{
        $test = $current + $token
        $tsz = $gfx.MeasureString($test, $fnt, [int]::MaxValue, $measureFmt)
        if ($tsz.Width -le $targetW -or $current -eq "") {{
            $current = $test
        }} else {{
            $result.Add($current.TrimEnd())
            $current = $token
        }}
        $csz = $gfx.MeasureString($current, $fnt, [int]::MaxValue, $measureFmt)
        if ($csz.Width -gt $maxW -and $current.Length -gt 1) {{
            $chars = $current.ToCharArray()
            $buf = ""
            foreach ($ch in $chars) {{
                $try = $buf + $ch
                $chsz = $gfx.MeasureString($try, $fnt, [int]::MaxValue, $measureFmt)
                if ($chsz.Width -gt $maxW -and $buf -ne "") {{
                    $result.Add($buf)
                    $buf = [string]$ch
                }} else {{
                    $buf = $try
                }}
            }}
            $current = $buf
        }}
    }}
    if ($current -ne "") {{ $result.Add($current.TrimEnd()) }}
    return $result.ToArray()
}}

# Wrap input lines
$wrappedInput = [System.Collections.Generic.List[string]]::new()
foreach ($rawLine in $inputLines) {{
    if ($rawLine -eq $null) {{ $rawLine = "" }}
    $wl = WrapLine $rawLine $tempGfx $font $maxWidth
    foreach ($w in $wl) {{ $wrappedInput.Add($w) }}
}}

# Wrap output lines
$wrappedOutput = [System.Collections.Generic.List[string]]::new()
foreach ($rawLine in $outputLines) {{
    if ($rawLine -eq $null) {{ $rawLine = "" }}
    $wl = WrapLine $rawLine $tempGfx $font $maxWidth
    foreach ($w in $wl) {{ $wrappedOutput.Add($w) }}
}}
$tempGfx.Dispose()
$tempBmp.Dispose()

# Line height
$tempBmp2 = New-Object System.Drawing.Bitmap(1,1)
$tempBmp2.SetResolution(100, 100)
$tempGfx2 = [System.Drawing.Graphics]::FromImage($tempBmp2)
$singleH = $font.GetHeight($tempGfx2)
$tempGfx2.Dispose()
$tempBmp2.Dispose()

$doc.add_PrintPage({{
    param($sender, $e)
    $bounds = $e.MarginBounds

    # Y positions: map canvas percentage (of total paper height) to graphics coords
    # OriginAtMargins=true so (0,0) is at margin corner; subtract margin to match canvas
    # Center each text block AT its designated Y%, not start it there
    $pgst = $e.PageSettings
    $paperH = if ($pgst.Landscape) {{ $pgst.PaperSize.Width }} else {{ $pgst.PaperSize.Height }}
    $inputBlockH  = $wrappedInput.Count  * $singleH
    $outputBlockH = $wrappedOutput.Count * $singleH
    $inputStartY  = [float][Math]::Max(0, $paperH * $inputYPct / 100.0 - $pgst.Margins.Top - $inputBlockH / 2.0)
    $outputStartY = [float][Math]::Max(0, $paperH * $outputYPct / 100.0 - $pgst.Margins.Top - $outputBlockH / 2.0)

    # Draw input block (center-aligned via StringFormat)
    $yPos = $inputStartY
    foreach ($line in $wrappedInput) {{
        if (($yPos + $singleH) -gt $bounds.Height) {{ break }}
        $lineRect = New-Object System.Drawing.RectangleF(0, $yPos, [float]$bounds.Width, $singleH)
        $e.Graphics.DrawString($line, $font, [System.Drawing.Brushes]::Black, $lineRect, $centerFmt)
        $yPos += $singleH
    }}

    # Separator line between blocks
    if ($drawSep -and $wrappedInput.Count -gt 0 -and $wrappedOutput.Count -gt 0) {{
        $sepY = [float](($yPos + $outputStartY) / 2)
        if ($sepY -gt $yPos -and $sepY -lt $outputStartY) {{
            $pen = New-Object System.Drawing.Pen([System.Drawing.Color]::Gray, 0.5)
            $x1 = [float]($bounds.Width * 0.15)
            $x2 = [float]($bounds.Width * 0.85)
            $e.Graphics.DrawLine($pen, $x1, $sepY, $x2, $sepY)
            $pen.Dispose()
        }}
    }}

    # Draw output block (center-aligned via StringFormat)
    $yPos = $outputStartY
    foreach ($line in $wrappedOutput) {{
        if (($yPos + $singleH) -gt $bounds.Height) {{ break }}
        $lineRect = New-Object System.Drawing.RectangleF(0, $yPos, [float]$bounds.Width, $singleH)
        $e.Graphics.DrawString($line, $font, [System.Drawing.Brushes]::Black, $lineRect, $centerFmt)
        $yPos += $singleH
    }}

    $e.HasMorePages = $false
}})

$doc.Print()
$centerFmt.Dispose()
$measureFmt.Dispose()
$font.Dispose()
$doc.Dispose()
'''

        encoded_cmd = base64.b64encode(ps_script.encode("utf-16-le")).decode("ascii")

        ps_result = subprocess.run(
            ["powershell", "-NoProfile", "-EncodedCommand", encoded_cmd],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if ps_result.returncode != 0:
            logger.warning("PrintDocument failed: %s", ps_result.stderr.strip())
            return False

        logger.info(
            "Printed positioned to %s (input_y=%.1f%%, output_y=%.1f%%)",
            printer_name, input_y_pct, output_y_pct,
        )
        return True

    except FileNotFoundError:
        logger.warning("powershell not found")
        return False
    except subprocess.TimeoutExpired:
        logger.warning("Print command timed out")
        return False
    except Exception as e:
        logger.warning("Print failed: %s", e)
        return False


def print_file(
    file_path: str | Path,
    printer_name: str,
    paper_size: str = "",
    landscape: bool = False,
    font_size: int = 12,
    font_name: str = "Malgun Gothic",
) -> bool:
    """Print a text file to the specified Windows printer.

    Reads the file and delegates to print_text().
    Returns True on success, False on failure. Never raises.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        logger.warning("Print skipped – file not found: %s", file_path)
        return False
    text = file_path.read_text(encoding="utf-8")
    return print_text(text, printer_name, paper_size, landscape, font_size, font_name)
