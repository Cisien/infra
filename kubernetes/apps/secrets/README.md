Generated SealedSecret files go in this directory.

Run `../scripts/port-wavelog-secrets.py` only after the Sealed Secrets
controller is healthy. Apply the generated files before `../wavelog.yaml`.
Do not place plain Kubernetes Secret files here.
