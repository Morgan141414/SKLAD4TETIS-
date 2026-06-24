# Server sync

SSH access is configured for:

```bash
ssh admin2@100.76.173.85
```

Project mirrors live in `server-projects/`, so they are visible in this VS Code workspace.

Pull a project from the server:

```bash
./scripts/pull-server-project.sh /home/admin2/mis mis
```

Push a local mirror back to the server:

```bash
./scripts/push-server-project.sh mis /home/admin2/mis
```

Known project candidates on the server:

```text
/home/admin2/mis
/home/admin2/S.A.N.A
/home/admin2/agregator
/home/admin2/work/MURMURMUR
```
