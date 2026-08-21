param(
    [string]$Log = "smtp_sink_log.jsonl"
)
# Ephemeral SMTP sink for live remediation proof. Stop with Stop-Process -Id $pid.
Set-Location $PSScriptRoot
uv run --with aiosmtpd python smtp_sink.py $Log 1025 *>&1 | Out-File -FilePath "smtp_sink_run.log" -Append
