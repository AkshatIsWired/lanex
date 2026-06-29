# Releasing LanEx — make the bundle independent & operational

LanEx is built on LibreLane but must keep working no matter what the LibreLane
project does upstream (move a tag, delete an old image, change an API). The whole
release flow is **one command** on a networked Docker host:

```sh
docker login ghcr.io          # once: a PAT with write:packages
VERSION=0.1.0 ./scripts/release.sh
```

That runs the **3-layer independence model** end to end. The single manual step
afterward — making the published package public — is deliberately left to you.

---

## Why this makes us independent (the core idea)

A built image is a **frozen filesystem snapshot**. The moment `docker build`
finishes, every tool (LibreLane, OpenROAD, Yosys, Magic, KLayout, Netgen,
iverilog, graphviz, GDS3D) and LanEx itself already live *inside* the image.
LibreLane could delete everything upstream and a `docker pull` of your image still
works — it never touches their servers again. Independence comes from **owning the
artifact**, not from version-pinning. (Pinning is a separate axis: it only governs
whether a *rebuild* is reproducible.)

| Layer | Script step | What it buys |
|-------|-------------|--------------|
| **1 — build = freeze** | `docker build` | Self-contained image; running it needs nobody's servers. |
| **2 — store where you control** | mirror base → `lanex-base`; push `lanex:<ver>`/`:latest` | Users `docker pull` forever; even **rebuilds** survive upstream deletion. |
| **3 — cold tarball** | `docker save \| gzip` → GitHub Release | Restore with **zero** registry. The last-resort backup. |

`base-image.lock` records the exact **@sha256: digest** of the mirrored base, so a
rebuild months later uses the byte-identical base. It is committed to git on
purpose. The tarball is **not** (it's huge — it lives on a GitHub Release).

---

## `scripts/release.sh`

```sh
VERSION=0.1.0 ./scripts/release.sh                 # full run
VERSION=0.1.0 ./scripts/release.sh --dry-run       # print the plan, change nothing
VERSION=0.1.0 OWNER=akshatiswired LIBRELANE_TAG=3.0.4 ./scripts/release.sh
```

| Flag | Effect |
|------|--------|
| `--dry-run` | Echo every command; touch nothing. |
| `--mirror` | Force a fresh base mirror + re-pin `base-image.lock`. |
| `--no-mirror` | Build straight from the upstream tag (skip Layer 2 base mirror). |
| `--no-archive` | Skip the cold tarball (Layer 3). |
| `--no-gh-release` | Don't create the GitHub Release / upload the tarball. |

Base selection: if `base-image.lock` exists it builds from that pinned digest;
otherwise it mirrors once. `--mirror` refreshes; `--no-mirror` ignores the lock.

What it does, in order:
1. **Mirror** `ghcr.io/librelane/librelane:3.0.4` → `ghcr.io/akshatiswired/lanex-base:3.0.4`, resolve its digest, write `base-image.lock`.
2. **Build** `lanex:0.1.0` + `lanex:latest` **from that pinned digest** (bakes in iverilog/graphviz/GDS3D).
3. **Push** both tags to `ghcr.io/akshatiswired/lanex`.
4. **Archive** `dist/lanex-0.1.0.tar.gz` (cold backup).
5. **GitHub Release** `v0.1.0` with the tarball attached (if `gh` is installed).

---

## The one manual step (security-gated)

The CI/`release.sh` push lands the package as **private** (it inherits repo
visibility). To let people pull without authenticating:

> GitHub → your profile → **Packages** → `lanex` → **Package settings** →
> **Change visibility** → Public.

This is **separate** from the repository's visibility — the **repo stays private**.
Per the project guardrail, nothing is flipped public without your explicit action;
that's why the script never does it for you.

---

## After release — what users do

```sh
curl -fsSL https://raw.githubusercontent.com/AkshatIsWired/lanex/main/install.sh | sh
lanex
```

Or directly:

```sh
docker pull ghcr.io/akshatiswired/lanex:0.1.0
docker run --rm -p 8765:8765 -v "$PWD/work:/work" ghcr.io/akshatiswired/lanex:0.1.0
# open http://localhost:8765
```

Offline / registry-down restore from the cold tarball:

```sh
gunzip -c lanex-0.1.0.tar.gz | docker load
```

---

## CI alternative

`.github/workflows/docker-publish.yml` builds + pushes on a `v*` tag or manual
dispatch. To make **CI** builds independent too, set a repo **variable**
`BASE_IMAGE` (Settings → Secrets and variables → Actions → Variables) to your
digest-pinned mirror from `base-image.lock`; the workflow uses it automatically,
no YAML edit required. `scripts/release.sh` remains the authoritative path because
it also mirrors the base and writes the cold tarball.
