# Keycloak for Railway (production mode, optimized build, NOVA realm imported on first start).
# Runtime env: KC_DB_URL, KC_DB_USERNAME, KC_DB_PASSWORD, KC_HOSTNAME (public https URL),
# KC_BOOTSTRAP_ADMIN_USERNAME/PASSWORD, NOVA_PUBLIC_URL, NOVA_OIDC_CLIENT_SECRET, NOVA_DEMO_PASSWORD.
# Optional second realm `orion` (NOV-103), OFF by default: ORION_REALM_IMPORT=true plus ORION_NOVA_PUBLIC_URL,
# ORION_ORBIT_PUBLIC_URL, ORION_FORGE_PUBLIC_URL, ORION_NOVA_CLIENT_SECRET, ORION_ORBIT_CLIENT_SECRET,
# ORION_FORGE_CLIENT_SECRET, ORION_NOVA_SERVICE_SECRET (secrets >= 32 characters). Imported only if the realm does not exist.
FROM quay.io/keycloak/keycloak:26.8 AS build
ENV KC_DB=postgres KC_HEALTH_ENABLED=true KC_METRICS_ENABLED=false
RUN /opt/keycloak/bin/kc.sh build

FROM quay.io/keycloak/keycloak:26.8
COPY --from=build /opt/keycloak/ /opt/keycloak/
# Created by the keycloak user (it owns data/) so the entrypoint can add a file to it at start; a COPY would make it root-owned.
RUN mkdir -p /opt/keycloak/data/import
COPY infrastructure/keycloak/nova-realm.json /opt/keycloak/data/import/nova-realm.json
# Shipped but inert: the entrypoint moves it to data/import only when ORION_REALM_IMPORT=true (otherwise a plain exec of kc.sh).
COPY infrastructure/keycloak/orion-realm.json /opt/keycloak/data/orion/orion-realm.json
COPY --chmod=0755 infrastructure/keycloak/docker-entrypoint.sh /opt/keycloak/bin/orion-entrypoint.sh
# TLS ends at the platform proxy; Keycloak trusts X-Forwarded-* and serves plain HTTP on $PORT.
ENV KC_HTTP_ENABLED=true KC_PROXY_HEADERS=xforwarded KC_HTTP_PORT=8080 \
    JAVA_OPTS_APPEND="-Djava.net.preferIPv4Stack=false -Djava.net.preferIPv6Addresses=true"
EXPOSE 8080
ENTRYPOINT ["/opt/keycloak/bin/orion-entrypoint.sh"]
CMD ["start", "--optimized", "--import-realm"]
