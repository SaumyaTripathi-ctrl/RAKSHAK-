#!/bin/sh
# Generate a DEV-ONLY CA and MQTT broker certificate. Idempotent.
#   usage: gen-dev-certs.sh [output_dir]        (default: ./out)
# Runs inside alpine (docker compose `certs` service) or on any host with openssl.
# Never commit the output; never use these certificates outside local development.
set -eu

OUT=${1:-./out}
DAYS=${CERT_DAYS:-825}
mkdir -p "$OUT"

if [ -f "$OUT/ca.crt" ] && [ -f "$OUT/server.crt" ] && [ -f "$OUT/server.key" ]; then
    echo "certs already present in $OUT"
    exit 0
fi

cd "$OUT"
openssl ecparam -name prime256v1 -genkey -noout -out ca.key
openssl req -x509 -new -key ca.key -sha256 -days "$DAYS" -subj "/O=Rakshak Dev/CN=Rakshak Dev CA" -out ca.crt

openssl ecparam -name prime256v1 -genkey -noout -out server.key
openssl req -new -key server.key -subj "/O=Rakshak Dev/CN=mosquitto" -out server.csr
cat > server.ext <<EOF
subjectAltName = DNS:mosquitto, DNS:localhost, IP:127.0.0.1
extendedKeyUsage = serverAuth
basicConstraints = CA:FALSE
EOF
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -sha256 -days "$DAYS" \
    -extfile server.ext -out server.crt
rm -f server.csr server.ext ca.srl

# The broker runs as a non-root user inside its container: keys must be readable there (dev only).
chmod 644 ca.crt server.crt server.key
chmod 600 ca.key
echo "generated dev certs in $OUT"
