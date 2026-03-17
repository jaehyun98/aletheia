"""Windows printer integration.

Uses PowerShell commands to list printers and print text files
on native Windows.
"""

import base64
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


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


def print_file(
    file_path: str | Path,
    printer_name: str,
    paper_size: str = "",
    landscape: bool = False,
    font_size: int = 12,
    font_name: str = "Malgun Gothic",
) -> bool:
    """Print a text file to the specified Windows printer.

    Uses .NET ``System.Drawing.Printing.PrintDocument`` via PowerShell to
    render text with configurable orientation and font size.

    Returns True on success, False on failure. Never raises.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        logger.warning("Print skipped – file not found: %s", file_path)
        return False

    try:
        # Convert WSL path to Windows path if running under WSL
        resolved = str(file_path.resolve())
        try:
            result = subprocess.run(
                ["wslpath", "-w", resolved],
                capture_output=True, text=True, timeout=5,
            )
            win_path = result.stdout.strip() if result.returncode == 0 else resolved
        except FileNotFoundError:
            win_path = resolved

        landscape_str = "$true" if landscape else "$false"

        # Build PowerShell script using .NET PrintDocument
        ps_script = f'''
Add-Type -AssemblyName System.Drawing

$filePath   = "{win_path}"
$printerName = "{printer_name}"
$paperSize  = "{paper_size}"
$landscape  = {landscape_str}
$fontSize   = {font_size}

$lines = [System.IO.File]::ReadAllLines($filePath, [System.Text.Encoding]::UTF8)

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

# Set small margins (unit: 1/100 inch, 30 = ~7.6mm)
$doc.DefaultPageSettings.Margins = New-Object System.Drawing.Printing.Margins(30, 30, 30, 30)

# Create font with style fallback for variable/non-standard fonts
$fontName = "{font_name}"
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
# StringFormat for MeasureString only (not used for DrawString to avoid padding shift)
$measureFmt = New-Object System.Drawing.StringFormat
$measureFmt.FormatFlags = [System.Drawing.StringFormatFlags]::NoWrap
$measureFmt.Trimming = [System.Drawing.StringTrimming]::None

# --- Word-wrap: break original lines into wrapped lines at word boundaries ---
# Use 100 DPI so 1 pixel = 1/100 inch, matching PaperSize/Margin units
$tempBmp = New-Object System.Drawing.Bitmap(1,1)
$tempBmp.SetResolution(100, 100)
$tempGfx = [System.Drawing.Graphics]::FromImage($tempBmp)
# Printable width from page settings (unit: 1/100 inch)
$ps = $doc.DefaultPageSettings
$pw = $ps.PaperSize.Width - $ps.Margins.Left - $ps.Margins.Right
if ($pw -lt 50) {{ $pw = 300 }}
$maxWidth = [float]$pw

function WrapLine($text, $gfx, $fnt, $maxW) {{
    if ([string]::IsNullOrEmpty($text)) {{ return @("") }}

    # If the whole line fits, return as-is
    $sz = $gfx.MeasureString($text, $fnt, [int]::MaxValue, $measureFmt)
    if ($sz.Width -le $maxW) {{ return @($text) }}

    $result = [System.Collections.Generic.List[string]]::new()
    # Split by spaces (works for Korean phrases separated by spaces & English words)
    $tokens = $text -split '(?<= )'  # split keeping trailing space with each token
    $current = ""

    foreach ($token in $tokens) {{
        $test = $current + $token
        $tsz = $gfx.MeasureString($test, $fnt, [int]::MaxValue, $measureFmt)
        if ($tsz.Width -le $maxW -or $current -eq "") {{
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
        $yPos = [float]($bounds.Top + ($pageHeight - $remainHeight) / 2)
    }} else {{
        $yPos = [float]$bounds.Top
    }}

    while ($script:lineIndex -lt $wrappedLines.Count) {{
        $line = $wrappedLines[$script:lineIndex]
        $lineHeight = $lineHeights[$script:lineIndex]

        if (($yPos + $lineHeight) -gt $bounds.Bottom) {{
            $e.HasMorePages = $true
            return
        }}

        # Measure actual text width, then manually center X and Y
        $sz = $e.Graphics.MeasureString($line, $font, [int]::MaxValue, $measureFmt)
        $textW = $sz.Width
        $x = [float]($bounds.Left + ($bounds.Width - $textW) / 2)
        $e.Graphics.DrawString($line, $font, [System.Drawing.Brushes]::Black, $x, $yPos)

        $yPos += $lineHeight
        $script:lineIndex++
    }}

    $e.HasMorePages = $false
}})

$doc.Print()
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

        logger.info("Printed: %s -> %s (landscape=%s, font=%d)", file_path.name, printer_name, landscape, font_size)
        return True

    except FileNotFoundError:
        logger.warning("powershell not found")
        return False
    except subprocess.TimeoutExpired:
        logger.warning("Print command timed out for %s", file_path.name)
        return False
    except Exception as e:
        logger.warning("Print failed for %s: %s", file_path.name, e)
        return False
