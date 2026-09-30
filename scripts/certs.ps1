# Generate dev-only MQTT certificates into infra\certs\out using a throwaway alpine container.
. "$PSScriptRoot\_env.ps1"
Test-Docker
$out = Join-Path $Root 'infra\certs\out'
New-Item -ItemType Directory -Force $out | Out-Null
Invoke-Checked 'docker' @('run', '--rm', '-v', "${out}:/certs", '-v', "$Root\infra\certs\gen-dev-certs.sh:/gen/gen.sh:ro",
    'alpine:3.20', 'sh', '-c', 'apk add --no-cache openssl >/dev/null && sh /gen/gen.sh /certs')
