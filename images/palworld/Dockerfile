FROM docker.io/cm2network/steamcmd:root

COPY --chown=steam:steam entrypoint.sh /usr/local/bin/palworld-entrypoint
RUN chmod 0755 /usr/local/bin/palworld-entrypoint

USER steam
WORKDIR /data
ENTRYPOINT ["/usr/local/bin/palworld-entrypoint"]
