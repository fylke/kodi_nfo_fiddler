FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

# Remove the base image's Yarn apt source; its GPG key can fail to verify
# in some network environments and it isn't needed for this project.
RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends mkvtoolnix \
    && rm -rf /var/lib/apt/lists/*