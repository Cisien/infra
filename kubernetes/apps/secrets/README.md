# Encrypted application secrets

This directory contains only encrypted `SealedSecret` manifests. These files are safe to version because the Sealed Secrets controller decrypts them only in the target cluster.

Do not add plain Kubernetes `Secret` manifests, kubeconfig files, API tokens, passwords, or private keys here.

Generate a replacement SealedSecret from a plain Secret in memory, then apply the encrypted result. Do not write the plain Secret to the repository or to a temporary file.

The repository pre-commit hooks scan staged content for hardcoded secrets and private keys. Gitleaks excludes encrypted SealedSecret payload paths only; it does not exclude ordinary YAML files.
