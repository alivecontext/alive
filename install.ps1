# =============================================================================
#  ALIVE for Windows -- installer
# =============================================================================
#
#  THIS SCRIPT IS NOT SIGNED. Read it before you run it. It is plain text:
#  open it in Notepad (right-click > Open with > Notepad) and read it, or
#  look at it on GitHub: https://github.com/alivecontext/alive/blob/main/install.ps1
#
#  What it does, in order. Each step is skipped if it is already done, so
#  running it again is safe:
#
#    1. Git for Windows   - checks for it; if missing, offers to install it
#                           with winget (Git.Git). This is the only step that
#                           may ask for administrator approval.
#    2. Python 3          - checks for a Python that really runs (not the
#                           Microsoft Store placeholder); if missing, offers
#                           to install the Python install manager with winget.
#    3. Claude Code       - if missing, offers to run Anthropic's official
#                           installer: irm https://claude.ai/install.ps1 | iex
#    4. PATH              - adds %USERPROFILE%\.local\bin to YOUR user PATH
#                           (where Claude Code lives). Nothing system-wide.
#    5. ALIVE plugin      - claude plugin marketplace add alivecontext/alive
#                           claude plugin install alive@alivecontext --scope user
#                           (user scope: the terminal and the Claude desktop
#                           app's Code tab both read it from ~\.claude)
#    6. Keep chats        - sets "cleanupPeriodDays": 999999 in your
#                           ~\.claude\settings.json so Claude Code stops
#                           deleting old sessions after 30 days. Merged in,
#                           other settings untouched, and the file is copied
#                           to a dated backup beside it first.
#    7. World folder      - makes %USERPROFILE%\alive if it is not there.
#
#  It looks for the Claude desktop app only to tell you about it. It never
#  installs or changes the desktop app.
#
#  It never deletes anything. The only things it downloads and runs are
#  Anthropic's Claude Code installer and packages installed through winget
#  (Microsoft's package manager). It does not need administrator rights
#  except for installing Git, and it does not change execution policy.
#
#  HOW TO RUN IT (from the folder you saved it in):
#
#      powershell -ExecutionPolicy Bypass -File .\install.ps1
#
#  "-ExecutionPolicy Bypass" applies to this one run only. Windows blocks
#  unsigned downloaded scripts by default, so double-clicking it or typing
#  .\install.ps1 on its own will usually be refused before it even starts.
#
#  Options:  -Yes      answer yes to every offer (no questions)
#            -NoPause  don't wait for Enter at the end
#
#  Works in Windows PowerShell 5.1 (built into Windows 10/11) and PowerShell 7.
#  Keep this file plain ASCII: Windows PowerShell 5.1 misreads other text.
# =============================================================================

# 'Continue', not 'Stop': under Windows PowerShell 5.1, 'Stop' turns any
# line a native program (winget, claude, py) writes to stderr into a fatal
# error. Native results are checked through $LASTEXITCODE instead, and the
# file steps below pass -ErrorAction Stop themselves.
$ErrorActionPreference = 'Continue'

# Options. No param() block, so the file also works as "irm ... | iex".
$script:AssumeYes = ($args -contains '-Yes') -or ($env:ALIVE_INSTALL_YES -eq '1')
$script:NoPause = ($args -contains '-NoPause')
$script:RunFromFile = [bool]$PSCommandPath
$script:Problems = New-Object System.Collections.Generic.List[string]
$script:RunCommand = 'powershell -ExecutionPolicy Bypass -File .\install.ps1'

function Say([string]$text) { Write-Host $text }
function Step([string]$text) { Write-Host ''; Write-Host "== $text" -ForegroundColor Cyan }
function Ok([string]$text) { Write-Host "   ok  $text" -ForegroundColor Green }
function Warn([string]$text) { Write-Host "   !!  $text" -ForegroundColor Yellow }
function Problem([string]$text) {
    Write-Host "   xx  $text" -ForegroundColor Red
    $script:Problems.Add($text) | Out-Null
}

function Ask([string]$question) {
    if ($script:AssumeYes) { Say "   $question [Y/n] y (-Yes)"; return $true }
    try {
        $answer = Read-Host "   $question [Y/n]"
    } catch {
        # Non-interactive host: take the default.
        return $true
    }
    return ($answer -eq '' -or $answer -match '^(y|yes)$')
}

function Refresh-Path {
    # Pick up PATH changes made by installers in this same window.
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = (@($machine, $user) | Where-Object { $_ }) -join ';'
    $local = Join-Path $env:USERPROFILE '.local\bin'
    if (($env:Path -split ';') -notcontains $local) { $env:Path = "$env:Path;$local" }
}

function Have-Winget {
    return [bool](Get-Command winget -ErrorAction SilentlyContinue)
}

function Winget-Install([string[]]$wingetArgs) {
    # Returns $true when winget reports success (or "already installed").
    # Out-Host: winget's text must not become this function's return value.
    & winget install @wingetArgs --accept-package-agreements --accept-source-agreements --disable-interactivity | Out-Host
    $code = $LASTEXITCODE
    # -1978335189 (0x8A15002B): no applicable upgrade / already installed.
    return ($code -eq 0 -or $code -eq -1978335189)
}

# -- 1. Git for Windows -------------------------------------------------------

function Find-GitBash {
    $candidates = @()
    if ($env:CLAUDE_CODE_GIT_BASH_PATH) { $candidates += $env:CLAUDE_CODE_GIT_BASH_PATH }
    $git = Get-Command git -ErrorAction SilentlyContinue
    if ($git) {
        # ...\Git\cmd\git.exe -> ...\Git\bin\bash.exe
        $gitRoot = Split-Path (Split-Path $git.Source -Parent) -Parent
        $candidates += (Join-Path $gitRoot 'bin\bash.exe')
    }
    $candidates += (Join-Path $env:ProgramFiles 'Git\bin\bash.exe')
    if (${env:ProgramFiles(x86)}) { $candidates += (Join-Path ${env:ProgramFiles(x86)} 'Git\bin\bash.exe') }
    $candidates += (Join-Path $env:LOCALAPPDATA 'Programs\Git\bin\bash.exe')
    foreach ($c in $candidates) {
        if ($c -and (Test-Path -LiteralPath $c -PathType Leaf)) { return $c }
    }
    return $null
}

function Ensure-Git {
    Step 'Git for Windows (ALIVE runs its hooks in Git Bash)'
    $bash = Find-GitBash
    if (-not $bash) {
        Warn 'Git for Windows is not installed.'
        if (-not (Have-Winget)) {
            Problem 'winget is missing, so Git cannot be installed from here. Install "App Installer" from the Microsoft Store, or Git from https://git-scm.com/download/win, then run this again.'
            return
        }
        if (-not (Ask 'Install Git for Windows now with winget? (Windows may ask for administrator approval)')) {
            Problem 'Git for Windows is needed. Install it, then run this again.'
            return
        }
        # Try a per-user install first (no admin); fall back to the normal one.
        $done = Winget-Install @('--id', 'Git.Git', '-e', '--source', 'winget', '--scope', 'user')
        if (-not $done) {
            Say '   Per-user install was not available; trying the standard install (may ask for admin).'
            $done = Winget-Install @('--id', 'Git.Git', '-e', '--source', 'winget')
        }
        Refresh-Path
        $bash = Find-GitBash
        if (-not $bash) {
            Problem 'Git did not install. Install it from https://git-scm.com/download/win, then run this again.'
            return
        }
    }
    Ok "Git Bash: $bash"
    # Claude Code finds Git Bash in the usual places; point it there anyway
    # when it is somewhere else (a per-user install). Must name bash.exe.
    $standard = Join-Path $env:ProgramFiles 'Git\bin\bash.exe'
    $current = [Environment]::GetEnvironmentVariable('CLAUDE_CODE_GIT_BASH_PATH', 'User')
    if ($bash -ne $standard -and -not ($current -and (Test-Path -LiteralPath $current))) {
        [Environment]::SetEnvironmentVariable('CLAUDE_CODE_GIT_BASH_PATH', $bash, 'User')
        $env:CLAUDE_CODE_GIT_BASH_PATH = $bash
        Ok "Set CLAUDE_CODE_GIT_BASH_PATH for your user to $bash"
    }
}

# -- 2. Python 3 --------------------------------------------------------------

function Test-Python([string]$exe, [string[]]$pre) {
    # True only if it runs and is Python 3. The Microsoft Store placeholder
    # (python.exe / python3.exe in WindowsApps) exits non-zero instead.
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { return $false }
    try {
        $out = & $exe @pre -c 'import sys; print(sys.version_info[0])' 2>$null
        return ($LASTEXITCODE -eq 0 -and "$out".Trim() -eq '3')
    } catch {
        return $false
    }
}

function Find-Python {
    if (Test-Python 'python3' @()) { return 'python3' }
    if (Test-Python 'py' @('-3')) { return 'py -3' }
    if (Test-Python 'python' @()) { return 'python' }
    return $null
}

function Ensure-Python {
    Step 'Python 3 (ALIVE hooks need it)'
    $py = Find-Python
    if ($py) { Ok "Python 3 runs as: $py"; return }
    $stub = Get-Command python3, python -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -like '*WindowsApps*' }
    if ($stub) { Warn 'The python on your PATH is the Microsoft Store placeholder, not Python.' }
    else { Warn 'Python 3 is not installed.' }
    if (-not (Have-Winget)) {
        Problem 'winget is missing, so Python cannot be installed from here. Install Python 3 from https://www.python.org/downloads/windows/ then run this again.'
        return
    }
    if (-not (Ask 'Install Python with winget? (no admin needed)')) {
        Problem 'Python 3 is needed. Install it, then run this again.'
        return
    }
    # The Python install manager (Microsoft Store source), then a runtime.
    if (Winget-Install @('9NQ7512CXL7T', '-e', '--source', 'msstore')) {
        Refresh-Path
        if (Get-Command py -ErrorAction SilentlyContinue) {
            & py install --configure -y | Out-Host
            Refresh-Path
        }
    }
    $py = Find-Python
    if (-not $py) {
        # Store source blocked (common on work PCs): python.org build, per user.
        Say '   Trying the python.org build instead (per user).'
        Winget-Install @('--id', 'Python.Python.3.13', '-e', '--source', 'winget', '--scope', 'user') | Out-Null
        Refresh-Path
        $py = Find-Python
    }
    if ($py) {
        Ok "Python 3 runs as: $py"
    } else {
        Problem 'Python 3 did not install or does not run. If python opens the Microsoft Store, turn off python.exe and python3.exe in Settings > Apps > Advanced app settings > App execution aliases, then run this again.'
    }
}

# -- 3 and 4. Claude Code and PATH -------------------------------------------

function Find-Claude {
    $exe = Join-Path $env:USERPROFILE '.local\bin\claude.exe'
    if (Test-Path -LiteralPath $exe -PathType Leaf) { return $exe }
    $cmd = Get-Command claude -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

function Ensure-Claude {
    Step 'Claude Code'
    $claude = Find-Claude
    if (-not $claude) {
        Warn 'Claude Code is not installed.'
        if (-not (Ask "Install it with Anthropic's official installer (irm https://claude.ai/install.ps1 | iex)?")) {
            Problem 'Claude Code is needed. Install it from https://claude.ai/download or https://code.claude.com, then run this again.'
            return $null
        }
        # Its own PowerShell process, so nothing it does can end this one.
        & powershell -NoProfile -ExecutionPolicy Bypass -Command 'irm https://claude.ai/install.ps1 | iex' | Out-Host
        $claude = Find-Claude
        if (-not $claude) {
            Problem 'The Claude Code installer did not finish. Run it yourself: irm https://claude.ai/install.ps1 | iex   then run this again.'
            return $null
        }
    }
    Ok "Claude Code: $claude"
    return $claude
}

function Ensure-UserPath {
    Step 'PATH (so "claude" works in a new window)'
    $dir = Join-Path $env:USERPROFILE '.local\bin'
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $true)
    try {
        # Raw value, so %VARS% in other entries stay as they are.
        $raw = [string]$key.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        $entries = @($raw -split ';' | Where-Object { $_ -ne '' })
        $already = $false
        foreach ($e in $entries) {
            $expanded = [Environment]::ExpandEnvironmentVariables($e).TrimEnd('\')
            if ($expanded -ieq $dir.TrimEnd('\')) { $already = $true }
        }
        if ($already) {
            Ok "$dir is already on your user PATH"
        } else {
            $new = (@($entries) + '%USERPROFILE%\.local\bin') -join ';'
            $key.SetValue('Path', $new, [Microsoft.Win32.RegistryValueKind]::ExpandString)
            Ok "Added $dir to your user PATH"
            Broadcast-EnvChange
        }
    } finally {
        $key.Close()
    }
    if (($env:Path -split ';') -notcontains $dir) { $env:Path = "$env:Path;$dir" }
}

function Broadcast-EnvChange {
    # Tell Explorer the environment changed, so new windows see the PATH.
    try {
        if (-not ('AliveInstall.Native' -as [type])) {
            Add-Type -Namespace AliveInstall -Name Native -MemberDefinition @'
[DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Auto)]
public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint Msg, UIntPtr wParam, string lParam, uint fuFlags, uint uTimeout, out UIntPtr lpdwResult);
'@
        }
        $result = [UIntPtr]::Zero
        [AliveInstall.Native]::SendMessageTimeout([IntPtr]0xffff, 0x1A, [UIntPtr]::Zero, 'Environment', 2, 5000, [ref]$result) | Out-Null
    } catch {
        Warn 'Could not notify Windows of the PATH change; sign out and in if "claude" is not found.'
    }
}

# -- 5. The ALIVE plugin -------------------------------------------------------

function Ensure-Plugin([string]$claude) {
    Step 'ALIVE plugin'
    if (-not $claude) { Problem 'Skipped: Claude Code is not installed.'; return }
    $markets = (& $claude plugin marketplace list 2>&1) -join "`n"
    if ($markets -match 'alivecontext') {
        & $claude plugin marketplace update alivecontext 2>&1 | Out-Null
        Ok 'Marketplace alivecontext is already added (refreshed)'
    } else {
        & $claude plugin marketplace add alivecontext/alive --scope user | Out-Host
        if ($LASTEXITCODE -ne 0) {
            Problem 'Could not add the ALIVE marketplace (claude plugin marketplace add alivecontext/alive). Check your internet connection and that Git is installed, then run this again.'
            return
        }
        Ok 'Added marketplace alivecontext/alive'
    }
    $plugins = (& $claude plugin list 2>&1) -join "`n"
    if ($plugins -match 'alive@alivecontext') {
        Ok 'alive@alivecontext is already installed'
        return
    }
    # User scope (the default, said out loud): the terminal and the desktop
    # app's Code tab share ~\.claude, so both see it.
    & $claude plugin install alive@alivecontext --scope user | Out-Host
    if ($LASTEXITCODE -ne 0) {
        Say '   First try failed; refreshing the ALIVE catalogue and trying once more.'
        & $claude plugin marketplace update alivecontext 2>&1 | Out-Null
        & $claude plugin install alive@alivecontext --scope user | Out-Host
    }
    $plugins = (& $claude plugin list 2>&1) -join "`n"
    if ($plugins -match 'alive@alivecontext') {
        Ok 'Installed alive@alivecontext (user scope)'
    } else {
        Problem 'Could not install the plugin (claude plugin install alive@alivecontext --scope user).'
    }
}

# -- 6. Keep chats (matches the Mac installer) ---------------------------------

function Ensure-KeepChats {
    Step 'Keep your Claude Code sessions (cleanupPeriodDays)'
    $conf = $env:CLAUDE_CONFIG_DIR
    if (-not $conf) { $conf = Join-Path $env:USERPROFILE '.claude' }
    $file = Join-Path $conf 'settings.json'
    $want = 999999
    $utf8 = New-Object System.Text.UTF8Encoding $false   # no BOM
    if (-not (Test-Path -LiteralPath $conf)) { New-Item -ItemType Directory -Path $conf -ErrorAction Stop | Out-Null }
    if (-not (Test-Path -LiteralPath $file)) {
        [IO.File]::WriteAllText($file, "{`n  `"cleanupPeriodDays`": $want`n}`n", $utf8)
        Ok "Made $file with cleanupPeriodDays $want"
        return
    }
    $text = [IO.File]::ReadAllText($file)
    $data = $null
    if ($text.Trim()) {
        try { $data = $text | ConvertFrom-Json -ErrorAction Stop } catch { $data = $null }
        if ($null -eq $data -or $data -isnot [System.Management.Automation.PSCustomObject]) {
            Warn "Left $file alone: it is not plain JSON. Add `"cleanupPeriodDays`": $want to it yourself to keep old sessions."
            return
        }
    } else {
        $data = New-Object psobject
    }
    $current = $data.PSObject.Properties['cleanupPeriodDays']
    if ($current -and ($current.Value -as [long]) -ge $want) {
        Ok 'Claude Code already keeps your sessions'
        return
    }
    $backup = "$file.alive-install-backup-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Copy-Item -LiteralPath $file -Destination $backup -ErrorAction Stop
    Ok "Backed up your settings to $backup"
    if ($current) { $current.Value = $want }
    else { $data | Add-Member -NotePropertyName 'cleanupPeriodDays' -NotePropertyValue $want }
    [IO.File]::WriteAllText($file, ($data | ConvertTo-Json -Depth 100) + "`n", $utf8)
    Ok "Set cleanupPeriodDays to $want (other settings unchanged)"
}

# -- The Claude desktop app (detected, never touched) -------------------------

function Find-DesktopApp {
    try {
        $pkg = Get-AppxPackage -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -like '*Claude*' -and $_.Publisher -like '*Anthropic*' } |
            Select-Object -First 1
        if ($pkg) { return $true }
    } catch { }
    $paths = @(
        (Join-Path $env:LOCALAPPDATA 'AnthropicClaude\claude.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Claude\Claude.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\claude-desktop\Claude.exe')
    )
    foreach ($p in $paths) { if (Test-Path -LiteralPath $p) { return $true } }
    $menu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
    if (Get-ChildItem -LiteralPath $menu -Filter 'Claude*.lnk' -Recurse -ErrorAction SilentlyContinue) { return $true }
    return $false
}

# -- 6. World folder -----------------------------------------------------------

function Ensure-World {
    Step 'Your ALIVE folder'
    $world = Join-Path $env:USERPROFILE 'alive'
    if (Test-Path -LiteralPath $world -PathType Container) {
        Ok "$world already exists"
    } else {
        New-Item -ItemType Directory -Path $world -ErrorAction Stop | Out-Null
        Ok "Made $world"
    }
    return $world
}

# -- Run -----------------------------------------------------------------------

function Install-Alive {
    Say 'ALIVE for Windows -- installer'
    Say 'Safe to run again: anything already done is skipped. Nothing is deleted.'

    if ($env:OS -ne 'Windows_NT') {
        Problem 'This installer is for Windows. On Mac or Linux follow the README.'
        return
    }
    if ($PSVersionTable.PSVersion.Major -lt 5) {
        Problem "PowerShell $($PSVersionTable.PSVersion) is too old; Windows PowerShell 5.1 or later is needed."
        return
    }
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Warn 'This window is running as administrator. That is not needed; a normal window is better.'
    }
    # Windows PowerShell 5.1 may default to old TLS; downloads need 1.2.
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    } catch { }

    Ensure-Git
    Ensure-Python
    $claude = Ensure-Claude
    Ensure-UserPath
    Ensure-Plugin $claude
    Ensure-KeepChats
    $world = Ensure-World
    $desktop = Find-DesktopApp

    Write-Host ''
    if ($script:Problems.Count -eq 0) {
        Write-Host 'ALIVE is installed.' -ForegroundColor Green
        Say ''
        Say 'ALIVE works in two places. Pick either:'
        Say ''
        Say ' 1. The terminal. Open a NEW PowerShell window (so it sees the new PATH):'
        Say "        cd `"$world`""
        Say '        claude'
        Say ''
        if ($desktop) {
            Say ' 2. The Claude desktop app (you have it). Quit it fully and reopen it,'
        } else {
            Say ' 2. The Claude desktop app, if you install it from https://claude.ai/download :'
        }
        Say '    click the Code tab (not the normal chat), and choose the folder:'
        Say "        $world"
        Say ''
        Say 'Sign in when asked (a Claude Pro or Max plan), then type:  /alive:world'
        Say 'ALIVE is not in the normal Claude chat, only in the terminal and the Code tab.'
    } else {
        Write-Host "Not finished: $($script:Problems.Count) step(s) need attention." -ForegroundColor Red
        foreach ($p in $script:Problems) { Say " - $p" }
        Say ''
        Say "Fix the above, then run the same command again: $script:RunCommand"
        Say 'If you are stuck, send back the output of:  claude doctor   and   claude plugin list'
    }
}

$failed = $false
try {
    Install-Alive
} catch {
    $failed = $true
    Write-Host ''
    Write-Host 'The ALIVE installer stopped with an error:' -ForegroundColor Red
    Write-Host "    $($_.Exception.Message)"
    Say ''
    Say 'Nothing was deleted. It is safe to run again; finished steps are skipped.'
    Say "Run it like this, from the folder it is in:  $script:RunCommand"
    Say 'If it fails again, send back this whole window plus the output of:  claude doctor   and   claude plugin list'
}

if ($script:RunFromFile -and -not $script:NoPause) {
    # Started by -File or "Run with PowerShell": keep the window open.
    try { Read-Host 'Press Enter to close' | Out-Null } catch { }
}

if ($script:RunFromFile -and ($failed -or $script:Problems.Count -gt 0)) { exit 1 }
# Under "irm ... | iex" there is no exit: it would close the person's window.
