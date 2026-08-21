$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$ImageName = "lk-ubuntu-build"
$ContainerName = "lk-ubuntu-build-artifacts"
$OutputDir = Join-Path $Root "dist\ubuntu-release"

Write-Host "Building Linux Ubuntu artifact image..."
docker build -f (Join-Path $Root "docker\Dockerfile.build-ubuntu") -t $ImageName $Root

Write-Host "Refreshing local output folder..."
if (Test-Path $OutputDir) {
    Remove-Item -Recurse -Force $OutputDir
}
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

Write-Host "Extracting compiled build from Docker..."
docker rm -f $ContainerName 2>$null | Out-Null
docker create --name $ContainerName $ImageName | Out-Null
docker cp "${ContainerName}:/out/." $OutputDir
docker rm -f $ContainerName | Out-Null

Write-Host "Ubuntu build exported to: $OutputDir"
