# Keycloak for Railway (production mode, optimized build, NOVA realm imported on first start).
# Runtime env: KC_DB_URL, KC_DB_USERNAME, KC_DB_PASSWORD, KC_HOSTNAME (public https URL),
# KC_BOOTSTRAP_ADMIN_USERNAME/PASSWORD, NOVA_PUBLIC_URL, NOVA_OIDC_CLIENT_SECRET, NOVA_DEMO_PASSWORD.
FROM quay.io/keycloak/keycloak:26.8 AS build
ENV KC_DB=postgres KC_HEALTH_ENABLED=true KC_METRICS_ENABLED=false
RUN /opt/keycloak/bin/kc.sh build

FROM quay.io/keycloak/keycloak:26.8
COPY --from=build /opt/keycloak/ /opt/keycloak/
COPY infrastructure/keycloak/nova-realm.json /opt/keycloak/data/import/nova-realm.json
# TLS ends at the platform proxy; Keycloak trusts X-Forwarded-* and serves plain HTTP on $PORT.
ENV KC_HTTP_ENABLED=true KC_PROXY_HEADERS=xforwarded KC_HTTP_PORT=8080 \
    JAVA_OPTS_APPEND="-Djava.net.preferIPv4Stack=false -Djava.net.preferIPv6Addresses=true"
EXPOSE 8080
ENTRYPOINT ["/opt/keycloak/bin/kc.sh"]
CMD ["start", "--optimized", "--import-realm"]
