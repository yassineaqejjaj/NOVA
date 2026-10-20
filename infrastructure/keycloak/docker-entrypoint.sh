#!/bin/bash
# Keycloak entrypoint of the Railway image (NOV-103).
#
# `orion-realm.json` ships in the image but is NOT imported by default: it is copied into the import directory only when
# ORION_REALM_IMPORT=true (pre-production first, never production without an explicit decision). With the variable unset
# or any other value this script is `exec kc.sh "$@"`: the container behaves exactly as before (realm `nova` only).
# `--import-realm` skips a realm that already exists: a second start never overwrites the realm.
set -euo pipefail

KC_HOME="${KC_HOME:-/opt/keycloak}"
REQUIRED=(
  ORION_NOVA_PUBLIC_URL ORION_ORBIT_PUBLIC_URL ORION_FORGE_PUBLIC_URL
  ORION_NOVA_CLIENT_SECRET ORION_ORBIT_CLIENT_SECRET ORION_FORGE_CLIENT_SECRET ORION_NOVA_SERVICE_SECRET
)

if [ "${ORION_REALM_IMPORT:-false}" = "true" ]; then
  missing=()
  for name in "${REQUIRED[@]}"; do
    value="${!name:-}"
    if [ -z "$value" ]; then
      missing+=("$name")
    elif [[ "$name" == *_SECRET ]] && [ "${#value}" -lt 32 ]; then
      missing+=("$name (shorter than 32 characters)")
    fi
  done
  if [ "${#missing[@]}" -gt 0 ]; then
    # Fail closed: an unresolved ${...} would otherwise be imported literally as a client secret or redirect URI.
    echo "ORION_REALM_IMPORT=true but: ${missing[*]}" >&2
    exit 1
  fi
  mkdir -p "$KC_HOME/data/import"
  cp "$KC_HOME/data/orion/orion-realm.json" "$KC_HOME/data/import/orion-realm.json"
  echo "orion realm import enabled (applies only if the realm does not exist yet)"
fi

exec "$KC_HOME/bin/kc.sh" "$@"
