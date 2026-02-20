#!/bin/bash
set -eo pipefail

host="${API_HOST:-localhost}"
port="${API_PORT:-8000}"

url="http://$host:$port/health"

if curl -f "$url"; then
    exit 0
else
    exit 1
fi
