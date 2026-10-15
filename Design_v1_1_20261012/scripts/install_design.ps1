param([string]$TargetRoot = 'C:\Users\Lenovo\Desktop\HarnessIR_Manual')
$ErrorActionPreference = 'Stop'
$SourceRoot = Split-Path -Parent $PSScriptRoot
$DesignName = 'Design_v1_1_20261012'
$Destination = Join-Path $TargetRoot $DesignName
$StagingName = $DesignName + '_staging_' + [guid]::NewGuid().ToString('N')
$Staging = Join-Path $TargetRoot $StagingName
try {
    if (Test-Path -LiteralPath $Destination) {
        throw "Destination already exists; no files were overwritten: $Destination"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $SourceRoot 'START_HERE.md') -PathType Leaf)) {
        throw 'Package is incomplete. Extract the whole ZIP first.'
    }
    if (-not (Test-Path -LiteralPath (Join-Path $SourceRoot 'PACKAGE_MANIFEST.json') -PathType Leaf)) {
        throw 'Package manifest is missing.'
    }
    # Verify package files before creating or copying anything into the user root.
    $Manifest = Get-Content -LiteralPath (Join-Path $SourceRoot 'PACKAGE_MANIFEST.json') -Raw | ConvertFrom-Json
    foreach ($Item in $Manifest.files) {
        $Candidate = [IO.Path]::GetFullPath((Join-Path $SourceRoot $Item.path))
        $Prefix = [IO.Path]::GetFullPath($SourceRoot).TrimEnd('\') + '\'
        if (-not $Candidate.StartsWith($Prefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw 'Invalid package path.'
        }
        if (-not (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
            throw "Missing package file: $($Item.path)"
        }
        $Hash = (Get-FileHash -LiteralPath $Candidate -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($Hash -ne $Item.sha256) { throw "Package checksum mismatch: $($Item.path)" }
    }
    New-Item -ItemType Directory -Path $TargetRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $Staging | Out-Null
    Get-ChildItem -LiteralPath $SourceRoot -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $Staging -Recurse
    }
    Move-Item -LiteralPath $Staging -Destination $Destination
    # Existing Data and case contents are never overwritten or moved.
    foreach ($Dir in @('cases', 'runtime', 'logs', 'models', 'preprocessing')) {
        $Path = Join-Path $TargetRoot $Dir
        if (-not (Test-Path -LiteralPath $Path)) {
            New-Item -ItemType Directory -Path $Path | Out-Null
        }
    }
    Write-Host "Design installed: $Destination"
    Write-Host 'Open index.html or START_HERE.md. This package does not install the Controller app.'
} catch {
    Write-Error $_
    exit 1
}
