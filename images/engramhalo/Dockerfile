# Pinned HIP runtime for the Qwen3.8-Flash-Next Strix Halo experiment.
# Source: Aristo94/EngramHalo.cpp at b08a77760fa73520d02d83b274f31b8fccf282bc.
FROM registry.fedoraproject.org/fedora:44 AS builder

RUN printf '%s\n' \
  '[rocm]' \
  'name=ROCm 7.14.0' \
  'baseurl=https://repo.amd.com/rocm/packages-multi-arch/rhel10/x86_64' \
  'enabled=1' \
  'priority=50' \
  'gpgcheck=1' \
  'gpgkey=https://repo.amd.com/rocm/packages-multi-arch/gpg/rocm.gpg' \
  > /etc/yum.repos.d/rocm.repo

RUN dnf -y --nodocs --setopt=install_weak_deps=False \
  install make gcc gcc-c++ cmake libcurl-devel ninja-build rdma-core-devel \
  amdrocm-core-devel7.14-gfx1151 git-core sudo rsync patch \
  && dnf clean all && rm -rf /var/cache/dnf/*

ENV ROCM_PATH=/opt/rocm \
    HIP_PATH=/opt/rocm \
    PATH=/opt/rocm/bin:/opt/rocm/core/bin:/opt/rocm/core/lib/llvm/bin:$PATH \
    LD_LIBRARY_PATH=/opt/rocm/core/lib/rocm_sysdeps/lib:/opt/rocm/core/lib

WORKDIR /opt/llama.cpp
ARG REPOSITORY=https://github.com/Aristo94/EngramHalo.cpp.git
ARG REVISION=b08a77760fa73520d02d83b274f31b8fccf282bc
RUN git clone --filter=blob:none "$REPOSITORY" . \
  && git checkout --detach "$REVISION" \
  && test "$(git rev-parse HEAD)" = "$REVISION" \
  && git show "$REVISION:docs/strix-halo/llama-cpp-25992-rocm-host-buffer.patch" > /tmp/host-buffer.patch \
  && git show "$REVISION:docs/strix-halo/llama-cpp-qwen38-per-buffer-mmap.patch" > /tmp/per-buffer-mmap.patch \
  && if git apply --check /tmp/host-buffer.patch; then \
       git apply /tmp/host-buffer.patch; \
     elif git apply --reverse --check /tmp/host-buffer.patch; then \
       echo 'host-buffer workaround already present'; \
     else \
       exit 1; \
     fi \
  && if git apply --check /tmp/per-buffer-mmap.patch; then \
       git apply /tmp/per-buffer-mmap.patch; \
     else \
       echo 'per-buffer mmap patch already present or obsolete'; \
     fi \
  && cmake -S . -B build \
       -DGGML_HIP=ON \
       -DAMDGPU_TARGETS=gfx1151 \
       -DCMAKE_BUILD_TYPE=Release \
       -DGGML_RPC=ON \
       -DROCM_PATH=/opt/rocm \
       -DHIP_PLATFORM=amd \
  && cmake --build build --config Release -- -j"$(nproc)" \
  && cmake --install build --config Release

RUN mkdir -p /usr/local/lib64 \
  && find /opt/llama.cpp/build -type f -name 'lib*.so*' -exec cp {} /usr/local/lib64/ \; \
  && ldconfig

FROM registry.fedoraproject.org/fedora-minimal:44

RUN printf '%s\n' \
  '[rocm]' \
  'name=ROCm 7.14.0' \
  'baseurl=https://repo.amd.com/rocm/packages-multi-arch/rhel10/x86_64' \
  'enabled=1' \
  'priority=50' \
  'gpgcheck=1' \
  'gpgkey=https://repo.amd.com/rocm/packages-multi-arch/gpg/rocm.gpg' \
  > /etc/yum.repos.d/rocm.repo

RUN microdnf -y --nodocs --setopt=install_weak_deps=0 \
  install bash ca-certificates libatomic libstdc++ libgcc libgomp libibverbs sudo \
  amdrocm-runtime7.14 amdrocm-blas7.14-gfx1151 radeontop procps-ng \
  && microdnf clean all && rm -rf /var/cache/dnf/* \
  && ln -s core-7.14 /opt/rocm/core \
  && ln -s core-7.14/bin /opt/rocm/bin \
  && ln -s core-7.14/include /opt/rocm/include \
  && ln -s core-7.14/lib /opt/rocm/lib \
  && ln -s core-7.14/libexec /opt/rocm/libexec \
  && ln -s core-7.14/lib/llvm /opt/rocm/llvm \
  && ln -s core-7.14/share /opt/rocm/share \
  && ln -s core-7.14/lib/llvm/amdgcn /opt/rocm/amdgcn

ENV ROCM_PATH=/opt/rocm \
    HIP_PATH=/opt/rocm \
    PATH=/opt/rocm/bin:/opt/rocm/core/bin:/opt/rocm/core/lib/llvm/bin:$PATH \
    LD_LIBRARY_PATH=/opt/rocm/core/lib/rocm_sysdeps/lib:/opt/rocm/core/lib

COPY --from=builder /usr/local/ /usr/local/
RUN echo '/usr/local/lib' > /etc/ld.so.conf.d/local.conf \
  && echo '/usr/local/lib64' >> /etc/ld.so.conf.d/local.conf \
  && echo '/opt/rocm/core/lib' > /etc/ld.so.conf.d/rocm.conf \
  && echo '/opt/rocm/core/lib/rocm_sysdeps/lib' >> /etc/ld.so.conf.d/rocm.conf \
  && ldconfig

ENTRYPOINT ["/usr/local/bin/llama-server"]
