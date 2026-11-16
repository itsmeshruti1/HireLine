param([Parameter(Mandatory=$true)][string]$Manifest, [Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$demoScript = Get-Content -LiteralPath $Manifest -Raw -Encoding UTF8 | ConvertFrom-Json
[System.IO.Directory]::CreateDirectory($OutputDirectory) | Out-Null
$narrator = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $narrator.SelectVoice($demoScript.voice)
    $narrator.Rate = 0
    $narrator.Volume = 100
    foreach ($chapter in $demoScript.chapters) {
        $wavePath = Join-Path $OutputDirectory ($chapter.id + '.wav')
        $narrator.SetOutputToWaveFile($wavePath)
        $narrator.Speak([string]$chapter.text)
        $narrator.SetOutputToNull()
        Write-Output ('Narrated ' + $chapter.id)
    }
} finally {
    $narrator.Dispose()
}
