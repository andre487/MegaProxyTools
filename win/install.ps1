# Run in a child scope so piping this script into iex leaves session settings intact.
& {
    $ErrorActionPreference = 'Stop'
    $temporary = $null
    try {
        $gitMode = $env:INSTALL_FROM_GIT
        if (-not $gitMode) { $gitMode = '0' }
        if ($gitMode -notin @('0', '1')) {
            throw 'INSTALL_FROM_GIT must be 0 or 1'
        }
        $ref = $env:MEGAPROXY_TOOLS_REF
        if (-not $ref) { $ref = 'main' }
        if ($ref.StartsWith('-')) { throw 'Invalid Git ref' }
        $prefix = $env:PREFIX
        if (-not $prefix) { $prefix = Join-Path $env:LOCALAPPDATA 'MegaProxyTools' }
        $prefix = [IO.Path]::GetFullPath($prefix)

        if ($gitMode -eq '1') {
            if (-not (Get-Command git -CommandType Application -ErrorAction SilentlyContinue)) {
                throw 'Git is required. Install it with: winget install --id Git.Git --exact'
            }
            function Invoke-Git {
                & git @args
                if ($LASTEXITCODE -ne 0) { throw 'Git installation failed' }
            }
            $repository = 'https://github.com/andre487/MegaProxyTools.git'
            $source = Join-Path $prefix 'src\MegaProxyTools'
            if (Test-Path -LiteralPath $source) {
                $inside = Invoke-Git -C $source rev-parse --is-inside-work-tree
                $relative = Invoke-Git -C $source rev-parse --show-prefix
                $origin = Invoke-Git -C $source config --get remote.origin.url
                if ($inside -ne 'true' -or $relative -or $origin -ne $repository) {
                    throw 'Source directory is not a MegaProxyTools checkout'
                }
                if (Invoke-Git -C $source status --porcelain) {
                    throw 'Source checkout has local changes; update it manually'
                }
            } else {
                New-Item -ItemType Directory -Force -Path (Split-Path $source) | Out-Null
                Invoke-Git clone -- $repository $source
            }
            Invoke-Git -C $source fetch origin $ref
            Invoke-Git -C $source checkout $ref --
            Invoke-Git -C $source merge --ff-only FETCH_HEAD
            & (Join-Path $source 'install.cmd') --git
        } else {
            $temporary = Join-Path ([IO.Path]::GetTempPath()) ('megaproxy-' + [guid]::NewGuid())
            New-Item -ItemType Directory -Path $temporary | Out-Null
            $archive = Join-Path $temporary 'source.zip'
            $url = 'https://codeload.github.com/andre487/MegaProxyTools/zip/' + [Uri]::EscapeDataString($ref)
            Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $archive
            $unpacked = Join-Path $temporary 'unpacked'
            Expand-Archive -LiteralPath $archive -DestinationPath $unpacked
            $roots = @(Get-ChildItem -LiteralPath $unpacked -Directory)
            if ($roots.Count -ne 1) { throw 'Invalid source archive' }
            & (Join-Path $roots[0].FullName 'install.cmd')
        }
        if ($LASTEXITCODE -ne 0) { throw 'Installation failed; see the instructions above' }
    } finally {
        if ($temporary -and (Test-Path -LiteralPath $temporary)) {
            # Only remove the unique directory created by this invocation under TEMP.
            $resolved = [IO.Path]::GetFullPath($temporary)
            $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
            if (-not $resolved.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
                throw 'Refusing to remove a directory outside TEMP'
            }
            Remove-Item -LiteralPath $resolved -Recurse -Force
        }
    }
}
